"""Offline causal contracts for private serial discovery; invented identities only."""

import importlib
import json
import subprocess
import time
from pathlib import Path

import pytest


def offline_child(argv, directory, timeout):
    started = time.time()
    outcome = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    receipt = {
        "argv": list(argv),
        "cwd": str(Path.cwd()),
        "started": started,
        "ended": time.time(),
        "exit": outcome.returncode,
        "stdout": outcome.stdout.decode("utf-8", errors="replace"),
        "stderr": outcome.stderr.decode("utf-8", errors="replace"),
    }
    (directory / ("offline-command-" + str(time.time_ns()) + ".json")).write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return outcome


def api():
    try:
        return importlib.import_module("wso_tvt_bridge.windows_local_device")
    except ModuleNotFoundError:
        pytest.fail("private local device controller missing")


def context(**changes):
    value = {
        "schemaVersion": 1,
        "version": "local-device-1",
        "generation": "a" * 32,
        "privateFilesPath": "/data/user/0/com.wso.tvt.localdevice/files",
        "singleId": "1234567890abcdef1234567890abcdef",
        "sourceNetworkType": 4,
    }
    value.update(changes)
    return json.dumps(value).encode()


def result(**changes):
    value = {
        "schemaVersion": 1,
        "version": "local-device-1",
        "generation": "a" * 32,
        "stage": "complete",
        "failure": "none",
        "deviceType": 20001,
        "nativeError": 0,
        "transportOpen": True,
        "greetingBytes": 64,
        "cleanup": "closed",
        "authenticated": False,
        "live": False,
    }
    value.update(changes)
    return json.dumps(value).encode()


def test_controller_exists_and_private_request_repr():
    m = api()
    r = m.PrivateDeviceRequest("inventedABC123", "KR", "a" * 32)
    assert "invented" not in repr(r)
    assert r.serial == "INVENTEDABC123"


@pytest.mark.parametrize("serial", ["", "x" * 64, "a-b", "한글", "x\x00y", True])
def test_serial_rejected_before_any_boundary(serial):
    with pytest.raises(ValueError):
        api().PrivateDeviceRequest(serial, "KR", "a" * 32)


@pytest.mark.parametrize(
    "change",
    [
        {"generation": "x"},
        {"budget_millis": 0},
        {"budget_millis": 120001},
        {"greeting_millis": 6000},
        {"greeting_bytes": 10241},
        {"country_code": "kr"},
        {"country_code": "AP"},
    ],
)
def test_request_bounds(change):
    with pytest.raises(ValueError):
        api().PrivateDeviceRequest(
            **(
                {"serial": "invented", "country_code": "KR", "generation": "a" * 32}
                | change
            )
        )


def test_factory_uses_private_context_single_id_and_wifi_mapping():
    m = api()
    r = m.PrivateDeviceRequest("invented", "KR", "a" * 32)
    packet = json.loads(m.private_packet(r, context()))
    assert packet["profile"]["model"] == "1234567890abcdef1234567890abcdef"
    assert packet["profile"]["nat2Host"] == "cli-nat20.autonatap.com"
    assert packet["profile"]["networkFlag"] == 1
    assert packet["profile"]["traversalMode"] == 0
    assert packet["profile"]["disableUPnP"] is False
    assert not {"username", "password", "commands"} & set(packet)
    for network in (0, 2, 3, 5):
        assert (
            json.loads(m.private_packet(r, context(sourceNetworkType=network)))[
                "profile"
            ]["networkFlag"]
            == 0
        )


@pytest.mark.parametrize(
    "change",
    [
        {"generation": "b" * 32},
        {"singleId": "model"},
        {"sourceNetworkType": True},
        {"sourceNetworkType": 1},
        {"privateFilesPath": "/tmp"},
        {"privateFilesPath": "/data/user/0/com.wso.tvt.localdevice/files/../x"},
        {"extra": "x"},
    ],
)
def test_context_identity_rejected(change):
    m = api()
    with pytest.raises(ValueError):
        m.private_packet(
            m.PrivateDeviceRequest("invented", "KR", "a" * 32), context(**change)
        )


def test_duplicate_context_rejected():
    m = api()
    with pytest.raises(ValueError):
        m.private_packet(
            m.PrivateDeviceRequest("invented", "KR", "a" * 32),
            context()[:-1] + b',"singleId":"duplicate"}',
        )


def test_open_and_partial_greeting_never_authentication():
    m = api()
    for kind in (3, 10001, 20001):
        parsed = m.parse_result(
            result(deviceType=kind, greetingBytes=17), "a" * 32, 10240
        )
        assert (
            parsed["transportOpen"]
            and not parsed["authenticated"]
            and not parsed["live"]
        )


@pytest.mark.parametrize(
    "change",
    [
        {"authenticated": True},
        {"live": True},
        {"deviceType": 8},
        {"greetingBytes": 10241},
        {"greetingBytes": 1, "transportOpen": False},
        {"generation": "b" * 32},
        {"nativeHandle": 42},
        {"cleanup": "proved"},
        {"deviceType": True},
    ],
)
def test_result_rejects_invented_acceptance(change):
    with pytest.raises(ValueError):
        api().parse_result(result(**change), "a" * 32, 10240)


def test_manifest_distinct_internet_only():
    import xml.etree.ElementTree as E

    root = Path(__file__).resolve().parents[2]
    path = root / "services/tvt-android-helper/android-local-device/AndroidManifest.xml"
    assert path.is_file(), "new helper manifest missing"
    xml = E.parse(path).getroot()
    ns = "{http://schemas.android.com/apk/res/android}"
    assert xml.attrib["package"] == "com.wso.tvt.localdevice"
    assert [p.attrib[ns + "name"] for p in xml.findall("uses-permission")] == [
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
    ]
    assert [n.tag for n in xml.find("application")] == ["activity"]


def test_java_activity_exists_for_inert_admission():
    path = (
        Path(__file__).resolve().parents[2]
        / "services/tvt-android-helper/android-local-device/src/com/wso/tvt/local/LocalDeviceProbeActivity.java"
    )
    assert path.is_file(), "private activity admission missing"


@pytest.mark.parametrize("mode", ["success", "watchdog", "watchdog_locked"])
def test_inert_java_admission_network_and_greeting(tmp_path, mode):
    # Wrong network precedence, bounds or callback/poll usage must change observable output.

    root = Path(__file__).resolve().parents[2]
    jdk = Path("C:/Android/tools/jdk-21.0.12.1+1/bin")
    sources = {
        "ErrnoException.java": "package android.system; public class ErrnoException extends Exception {}",
        "Os.java": "package android.system; public class Os {public static void rename(String a,String b)throws ErrnoException {try {java.nio.file.Files.move(java.nio.file.Paths.get(a),java.nio.file.Paths.get(b),java.nio.file.StandardCopyOption.REPLACE_EXISTING,java.nio.file.StandardCopyOption.ATOMIC_MOVE);}catch(java.io.IOException e){throw new ErrnoException();}}}",
        "Activity.java": """package android.app; public class Activity { public static final String CONNECTIVITY_SERVICE="connectivity"; public static java.io.File files; public void onCreate(android.os.Bundle b){} public void finish(){} public java.io.File getFilesDir(){return files;} public android.content.Intent getIntent(){return new android.content.Intent();} public Object getSystemService(String s){android.net.ConnectivityManager c=new android.net.ConnectivityManager();c.active=new android.net.NetworkInfo();c.active.type=1;return c;} }""",
        "Intent.java": 'package android.content; public class Intent {public String getStringExtra(String s){return s.equals("phase")?"context":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";}}',
        "Bundle.java": "package android.os; public class Bundle {}",
        "Process.java": "package android.os; public class Process { public static volatile int killed; public static int myPid(){return 7;} public static void killProcess(int p){killed=p;}}",
        "SystemClock.java": 'package android.os; public class SystemClock { public static long elapsedRealtime(){return System.nanoTime()/1000000*(Long.getLong("clockScale",1L));}}',
        "NetworkInfo.java": """package android.net; public class NetworkInfo { public enum State {CONNECTED,CONNECTING,DISCONNECTED} public int type,subtype; public boolean available=true; public State state=State.CONNECTED; public String name=""; public boolean isAvailable(){return available;} public State getState(){return state;} public int getType(){return type;} public int getSubtype(){return subtype;} public String getSubtypeName(){return name;} }""",
        "ConnectivityManager.java": """package android.net; public class ConnectivityManager { public NetworkInfo active, ethernet; public NetworkInfo getActiveNetworkInfo(){return active;} public NetworkInfo getNetworkInfo(int t){return ethernet;} }""",
        "JniLocalSerialDriver.java": """package com.wso.tvt.local; public class JniLocalSerialDriver implements LocalSerialDriver { public static int alloc,discover,open,send; int reads; public static JniLocalSerialDriver createAndroid(){return new JniLocalSerialDriver();} public long allocate(){alloc++;if(Boolean.getBoolean("blocked")){try{Thread.sleep(2000);}catch(InterruptedException e){}}return 123;} public void bind(long e,Callbacks c){} public void removeCallbacks(long e){} public int discover(long e,LocalSerialConfig c){discover++;return 20001;} public int error(long e){return 0;} public int openTransport(long e,LocalSerialConfig c){open++;return 0;} public int connectType(long e){return 1;} public int send(long e,byte[] b,int n){send++;throw new AssertionError();} public int receive(long e,byte[] b,int n){int want=reads++==0?9:reads==2?55:0;for(int i=0;i<want;i++)b[i]=(byte)i;return want;} public boolean interrupt(long e){return true;} public boolean destroy(long e){return true;} }""",
        "Harness.java": r"""package com.wso.tvt.local;
import java.io.*; import java.nio.file.*; import java.nio.charset.*; import java.util.*;
public class Harness {
 public static void main(String[] args)throws Exception {
  android.app.Activity.files=new File(args[0]) {public String getCanonicalPath(){return "/data/user/0/com.wso.tvt.localdevice/files";}};
  Files.write(new File(android.app.Activity.files,"SINGLE_ID").toPath(),"1234567890abcdef1234567890abcdef".getBytes(StandardCharsets.UTF_8));
  LocalDeviceProbeActivity a=new LocalDeviceProbeActivity(); a.onCreate(null);
  String original=LocalDeviceProbeActivity.singleId(android.app.Activity.files);
  if(!original.equals(LocalDeviceProbeActivity.singleId(android.app.Activity.files)))throw new AssertionError("single id changed");
  byte[] packet=Files.readAllBytes(Paths.get(args[1]));
  Map<String,Object> request=LocalDeviceProbeActivity.parse(packet);
  Map<String,Object> context=LocalDeviceProbeActivity.parse(Files.readAllBytes(Paths.get(args[2])));
  LocalDeviceProbeActivity.admit(request,context,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  Map<String,Object> profile=(Map<String,Object>)request.get("profile");
  profile.put("nat2Host","cli-nat20.autonat.us");
  try{LocalDeviceProbeActivity.admit(request,context,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");throw new AssertionError("country mismatch");}catch(IllegalArgumentException ok){}
  profile.put("nat2Host","cli-nat20.autonatap.com");
  profile.put("model","Build.MODEL");
  try{LocalDeviceProbeActivity.admit(request,context,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");throw new AssertionError("model");}catch(IllegalArgumentException ok){}
  profile.put("model",context.get("singleId"));
  for(String bad:new String[]{"{\"a\":1,\"a\":2}","{\"a\":[]}","{\"a\":1.0}","{\"a\":01}"}){
   try{LocalDeviceProbeActivity.parse(bad.getBytes(StandardCharsets.UTF_8));throw new AssertionError("parser accepted");}catch(IllegalArgumentException ok){}
  }
  android.net.ConnectivityManager cm=new android.net.ConnectivityManager(); cm.active=new android.net.NetworkInfo();cm.active.type=1;
  cm.ethernet=new android.net.NetworkInfo();cm.ethernet.state=android.net.NetworkInfo.State.CONNECTING;
  if(LocalDeviceProbeActivity.sourceNetworkType(cm)!=5)throw new AssertionError("ethernet precedence");
  cm.ethernet=null;if(LocalDeviceProbeActivity.sourceNetworkType(cm)!=4)throw new AssertionError("wifi");
  cm.active.available=false;if(LocalDeviceProbeActivity.sourceNetworkType(cm)!=0)throw new AssertionError("availability");
  cm.active.available=true;cm.active.type=9;
  if(LocalDeviceProbeActivity.sourceNetworkType(cm)!=0)throw new AssertionError("inactive ethernet must be unknown");
  if(LocalDeviceProbeActivity.networkMapping(0,16,"")!=2 || LocalDeviceProbeActivity.networkMapping(0,17,"")!=3 || LocalDeviceProbeActivity.networkMapping(0,20,"")!=3 || LocalDeviceProbeActivity.networkMapping(0,19,"WCDMA")!=3)throw new AssertionError("subtypes");
  Files.write(new File(android.app.Activity.files,"request.json").toPath(),packet);
  Files.write(new File(android.app.Activity.files,"context.json").toPath(),Files.readAllBytes(Paths.get(args[2])));
  java.lang.reflect.Field gen=LocalDeviceProbeActivity.class.getDeclaredField("generation");gen.setAccessible(true);gen.set(a,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  java.lang.reflect.Method attempt=LocalDeviceProbeActivity.class.getDeclaredMethod("attempt");attempt.setAccessible(true);
  if(args[3].startsWith("watchdog")) {
   System.setProperty("clockScale","100");System.setProperty("blocked","true");
   Thread stuck=new Thread(()->{try{attempt.invoke(a);}catch(Exception e){throw new AssertionError(e);}});stuck.setDaemon(true);stuck.start();
   long until=System.nanoTime()+2000000000L;
   while(JniLocalSerialDriver.alloc==0 && System.nanoTime()<until)Thread.sleep(1);
   if(args[3].equals("watchdog_locked")) {
    java.lang.reflect.Field gate=LocalDeviceProbeActivity.class.getDeclaredField("outputLock");gate.setAccessible(true);
    synchronized(gate.get(a)) {while(android.os.Process.killed==0 && System.nanoTime()<until)Thread.sleep(5);}
   } else while(android.os.Process.killed==0 && System.nanoTime()<until)Thread.sleep(5);
   if(android.os.Process.killed!=7)throw new AssertionError("watchdog must kill only self");
   Thread.sleep(30); // Only inert syscall returns; real kill would end this process immediately.
   System.out.write(Files.readAllBytes(new File(android.app.Activity.files,"result.json").toPath()));return;
  }
  attempt.invoke(a);
  if(JniLocalSerialDriver.alloc!=1 || JniLocalSerialDriver.discover!=1 || JniLocalSerialDriver.open!=1 || JniLocalSerialDriver.send!=0)throw new AssertionError("one attempt/no sends: "+new String(Files.readAllBytes(new File(android.app.Activity.files,"result.json").toPath()),StandardCharsets.UTF_8));
  byte[] greeting=Files.readAllBytes(new File(android.app.Activity.files,"greeting.bin").toPath());if(greeting.length!=64)throw new AssertionError("fragmented greeting");
  System.out.write(Files.readAllBytes(new File(android.app.Activity.files,"result.json").toPath()));
 }
}""",
    }
    paths = []
    for name, contents in sources.items():
        p = tmp_path / name
        p.write_text(contents, encoding="utf-8")
        paths.append(str(p))
    real = root / "services/tvt-android-helper/src/main/java/com/wso/tvt/local"
    paths += [
        str(real / n)
        for n in (
            "LocalSerialConfig.java",
            "LocalSerialDriver.java",
            "LocalSerialTransport.java",
        )
    ]
    paths.append(
        str(
            root
            / "services/tvt-android-helper/android-local-device/src/com/wso/tvt/local/LocalDeviceProbeActivity.java"
        )
    )
    compile_result = offline_child(
        (str(jdk / "javac.exe"), "--release", "8", "-d", str(tmp_path), *paths),
        tmp_path,
        15,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    m = api()
    request = m.PrivateDeviceRequest(
        "invented", "KR", "a" * 32, greeting_millis=200, budget_millis=1000
    )
    packet = tmp_path / "packet.json"
    packet.write_bytes(m.private_packet(request, context()))
    ctx = tmp_path / "ctx.json"
    ctx.write_bytes(context())
    execution = offline_child(
        (
            str(jdk / "java.exe"),
            "-cp",
            str(tmp_path),
            "com.wso.tvt.local.Harness",
            str(tmp_path),
            str(packet),
            str(ctx),
            mode,
        ),
        tmp_path,
        5,
    )
    assert execution.returncode == 0, execution.stderr.decode()
    safe = m.parse_result(execution.stdout, "a" * 32, 10240)
    if mode.startswith("watchdog"):
        assert safe["stage"] == "deadline" and safe["cleanup"] == "pending"
        assert safe["failure"] == "deadline" and safe["transportOpen"] is False
    else:
        assert (
            safe["transportOpen"]
            and safe["greetingBytes"] == 64
            and safe["cleanup"] == "closed"
        )
    assert safe["authenticated"] is False and safe["live"] is False


def test_private_runner_stream_and_bounded_capture():
    import sys

    m = api()
    runner = m.PrivateRunner()
    outcome = runner.run(
        (
            sys.executable,
            "-c",
            "import sys; b=sys.stdin.buffer.read(); sys.stdout.buffer.write(b)",
        ),
        2,
        input_bytes=b"INVENTEDPRIVATE",
    )
    assert outcome.stdout == b"INVENTEDPRIVATE"
    assert "INVENTEDPRIVATE" not in json.dumps(runner.receipts)
    over = runner.run(
        (sys.executable, "-c", 'import sys;sys.stdout.buffer.write(b"x"*20000)'),
        2,
        max_bytes=10240,
    )
    assert over.overflow and len(over.stdout) == 10240
    timed = runner.run((sys.executable, "-c", "import time;time.sleep(2)"), 0.05)
    assert timed.timed_out and timed.reaped


class DeviceBoundary:
    def __init__(self, m, *, present=False, uid_change=False, cleanup_fail=False):
        self.m = m
        self.calls = []
        self.installed = False
        self.uid_reads = 0
        self.present = present
        self.uid_change = uid_change
        self.cleanup_fail = cleanup_fail
        self.inputs = []
        self.started = False

    def run(self, argv, timeout, *, max_bytes=4096, input_bytes=None):
        args = argv[7:]
        self.calls.append(args)
        raw = b""
        if args[:3] == ("shell", "getprop", "sys.boot_completed"):
            raw = b"1\n"
        elif args[:3] == ("shell", "getprop", "ro.build.version.sdk"):
            raw = b"30\n"
        elif args[:3] == ("shell", "getprop", "ro.product.cpu.abilist"):
            raw = b"arm64-v8a,armeabi-v7a\n"
        elif args[:3] == ("shell", "dumpsys", "package"):
            self.uid_reads += 1
            if self.installed or self.present:
                uid = 12346 if self.uid_change and self.started else 12345
                raw = f"Packages:\n  Package [com.wso.tvt.localdevice] (a):\n    userId={uid}\n".encode()
            else:
                raw = b"Dexopt state:\n  Unable to find package: com.wso.tvt.localdevice\n"
        elif args[0] == "install":
            self.installed = True
            raw = b"Success\n"
        elif args[:2] == ("shell", "am") and "attempt" in args:
            self.started = True
        elif args[0] == "exec-in":
            self.inputs.append(input_bytes)
        elif args[0] == "exec-out":
            name = args[-1]
            if name == "files/context.json":
                raw = context()
            elif name == "files/request.json" and self.inputs:
                raw = self.inputs[-1]
            elif name == "files/result.json":
                raw = result(cleanup="quarantined")
            elif name == "files/greeting.bin":
                raw = bytes(range(64))
        elif args[:3] == ("shell", "am", "force-stop") and self.cleanup_fail:
            return self.m.custody.CommandOutcome(1, b"", False, True)
        elif args[0] == "uninstall":
            self.installed = False
            raw = b"Success\n"
        return self.m.custody.CommandOutcome(0, raw, False, True)


def controller_config(m, tmp_path):
    import tempfile

    staging = Path(tempfile.mkdtemp(prefix="device-private-", dir="C:/Windows/Temp"))
    return m.DeviceProbeConfig(
        Path("C:/invented/adb.exe"),
        tmp_path / "build.json",
        tmp_path / "review.json",
        "development-debug",
        staging,
        "google-translation-development",
    )


@pytest.mark.parametrize(
    "mode",
    [
        "delivered",
        "missing",
        "partial",
        "altered",
        "generation",
        "diagnostic",
        "uid_write",
        "uid_read",
        "overflow",
        "read_failed",
    ],
)
def test_private_delivery_exact_argv_and_readback_before_attempt(
    tmp_path, monkeypatch, mode
):
    # Literal script quotes break the inner shell tokenization. Exit0 alone,
    # prefix/length-only validation, or missing UID recheck must admit no attempt.
    import hashlib
    import sys
    from dataclasses import asdict

    m = api()
    cfg = controller_config(m, tmp_path)
    artifact = tmp_path / "helper.apk"
    artifact.write_bytes(b"invented reviewed helper")
    identity = m.custody._BuildArtifact(
        artifact,
        artifact.stat().st_size,
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(m, "_load_reviewed", lambda c: identity)
    remote = tmp_path / "remote"
    remote.mkdir()
    child_script = tmp_path / "inert_exec.py"
    child_script.write_text(
        """import pathlib, shlex, sys
root = pathlib.Path(sys.argv[1])
# Model exec service shell escaping of argv followed by the remote outer shell.
# This is a limited lexical fixture, not a real adb/Android execution claim.
argv = shlex.split(shlex.join(sys.argv[2:]), posix=True)
assert argv[:5] == ["exec-in", "run-as", "com.wso.tvt.localdevice", "sh", "-c"]
assert len(argv) == 6
raw = sys.stdin.buffer.read(4097)
assert len(raw) <= 4096
# The inner sh -c receives one script argument. Literal outer quote characters
# turn the entire script into one command-name token; they are not host syntax.
lexer = shlex.shlex(argv[5], posix=True, punctuation_chars=";>")
lexer.whitespace_split = True
tokens = list(lexer)
if tokens == ["umask", "077", ";", "cat", ">", "files/request.json"]:
    (root / "request.json").write_bytes(raw)
# Deliberately return zero even for a non-executed script, like the observed
# adb exec transport. Only actual request bytes can establish delivery.
""",
        encoding="utf-8",
    )

    class DeliveryBoundary(DeviceBoundary):
        def __init__(self):
            super().__init__(m)
            self.child = m.PrivateRunner()
            self.changed = False
            self.readback_calls = 0
            self.readback_uid_after = False

        def run(self, argv, timeout, *, max_bytes=4096, input_bytes=None):
            args = argv[7:]
            if args[:3] == ("shell", "dumpsys", "package"):
                if self.changed:
                    self.calls.append(args)
                    return m.custody.CommandOutcome(
                        0,
                        b"Packages:\n  Package [com.wso.tvt.localdevice] (a):\n    userId=12346\n",
                        False,
                        True,
                    )
                if self.readback_calls:
                    self.readback_uid_after = True
            if args[0] == "exec-in":
                self.calls.append(args)
                self.inputs.append(input_bytes)
                outcome = self.child.run(
                    (sys.executable, str(child_script), str(remote), *args),
                    timeout,
                    input_bytes=input_bytes,
                )
                path = remote / "request.json"
                if path.exists():
                    if mode == "missing":
                        path.unlink()
                    elif mode == "partial":
                        path.write_bytes(path.read_bytes()[:-1])
                    elif mode == "altered":
                        path.write_bytes(
                            path.read_bytes().replace(
                                b"INVENTEDPRIVATE", b"INVENTEDPRIVATX"
                            )
                        )
                    elif mode == "generation":
                        path.write_bytes(
                            path.read_bytes().replace(b"a" * 32, b"b" * 32)
                        )
                if mode == "uid_write":
                    self.changed = True
                return outcome
            if args == ("exec-out", "run-as", m.PACKAGE, "cat", "files/request.json"):
                self.calls.append(args)
                self.readback_calls += 1
                assert max_bytes == 4096 and 0 < timeout <= cfg.command_seconds
                path = remote / "request.json"
                raw = (
                    path.read_bytes()
                    if path.exists()
                    else b"cat: files/request.json: No such file or directory\r\n"
                )
                if mode == "diagnostic":
                    raw = b"cat: files/request.json: No such file or directory\r\n"
                if mode == "uid_read":
                    self.changed = True
                return m.custody.CommandOutcome(
                    1 if mode == "read_failed" else 0,
                    raw,
                    False,
                    True,
                    overflow=mode == "overflow",
                )
            if args[:3] == ("shell", "am", "start") and "attempt" in args:
                # Even the simulated Activity reports the actual missing-file failure.
                self.started = True
                self.calls.append(args)
                return m.custody.CommandOutcome(0, b"", False, True)
            if args[0] == "exec-out" and args[-1] == "files/result.json":
                self.calls.append(args)
                raw = (
                    result(cleanup="quarantined")
                    if (remote / "request.json").exists()
                    else result(
                        failure="io",
                        deviceType=0,
                        transportOpen=False,
                        greetingBytes=0,
                        cleanup="quarantined",
                    )
                )
                return m.custody.CommandOutcome(0, raw, False, True)
            return super().run(
                argv, timeout, max_bytes=max_bytes, input_bytes=input_bytes
            )

    boundary = DeliveryBoundary()
    request = m.PrivateDeviceRequest("inventedprivate", "KR", "a" * 32)
    try:
        out = m.run_device_probe(cfg, request, runner=boundary)
        if mode == "delivered":
            assert out.failure == "none" and boundary.started
            assert boundary.readback_calls == 1 and boundary.readback_uid_after
            assert (remote / "request.json").read_bytes() == m.private_packet(
                request, context()
            )
            assert out.device["deviceType"] == 20001
        else:
            expected = {
                "uid_write": "package_identity",
                "uid_read": "package_identity",
                "overflow": "child_output_bound",
                "read_failed": "child_failed",
            }.get(mode, "request_delivery")
            assert out.failure == expected
            assert not boundary.started and not out.device
        if mode.startswith("uid_"):
            assert out.package_cleanup == "uncertain"
            assert not any(
                c[:3] == ("shell", "am", "force-stop") or c[0] == "uninstall"
                for c in boundary.calls
            )
        else:
            assert (
                out.package_cleanup == "confirmed_absent"
                and out.staging_cleanup == "removed"
            )
        safe = json.dumps([boundary.calls, boundary.child.receipts, asdict(out)])
        assert (
            "INVENTEDPRIVATE" not in safe
            and "1234567890abcdef1234567890abcdef" not in safe
        )
        assert len(boundary.inputs) == 1
        assert json.loads(boundary.inputs[0])["generation"] == "a" * 32
    finally:
        boundary.child.wait_for_ownership()
        for directory in cfg.staging_root.iterdir():
            assert directory.parent.resolve() == cfg.staging_root.resolve()
            for item in directory.iterdir():
                assert item.is_file() and not item.is_symlink()
                item.unlink()
            directory.rmdir()
        cfg.staging_root.rmdir()


@pytest.mark.parametrize(
    "mode",
    [
        "context_finish",
        "attempt_no_draw",
        "delayed",
        "context_stale",
        "context_partial",
        "context_invalid",
        "result_stale",
        "result_partial",
        "result_invalid",
        "context_missing",
        "result_missing",
        "progress_only",
        "uid_context_read",
        "uid_result_read",
        "context_late",
        "result_late",
    ],
)
def test_async_readiness_scoped_deadline_and_private_input(tmp_path, monkeypatch, mode):
    # Restoring -W, admitting file presence, removing post-read UID proof, or
    # resetting the deadline per poll must fail this real controller lifecycle.
    import hashlib
    from dataclasses import asdict
    from types import SimpleNamespace

    m = api()
    cfg = controller_config(m, tmp_path)
    artifact = tmp_path / "helper.apk"
    artifact.write_bytes(b"invented reviewed helper")
    identity = m.custody._BuildArtifact(
        artifact,
        artifact.stat().st_size,
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(m, "_load_reviewed", lambda c: identity)
    now = [100.0]
    monkeypatch.setattr(
        m,
        "time",
        SimpleNamespace(
            monotonic=lambda: now[0],
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        ),
    )

    class ReadinessBoundary(DeviceBoundary):
        def __init__(self):
            super().__init__(m)
            self.reads = {"context": 0, "result": 0}
            self.changed = False
            self.launches = {}
            self.phase_commands = []

        def run(self, argv, timeout, *, max_bytes=4096, input_bytes=None):
            args = argv[7:]
            if args[:3] == ("shell", "am", "start"):
                phase = args[args.index("phase") + 1]
                self.launches[phase] = now[0]
                if "-W" in args and (
                    (mode == "context_finish" and phase == "context")
                    or (mode == "attempt_no_draw" and phase == "attempt")
                ):
                    self.calls.append(args)
                    now[0] += timeout
                    return m.custody.CommandOutcome(1, b"", True, True)
                # Scheduling is acknowledged; no context/result is ready yet.
                now[0] += 0.25
                return super().run(argv, timeout, max_bytes=max_bytes)
            if self.changed and args[:3] == ("shell", "dumpsys", "package"):
                self.calls.append(args)
                return m.custody.CommandOutcome(
                    0,
                    b"Packages:\n  Package [com.wso.tvt.localdevice] (a):\n    userId=12346\n",
                    False,
                    True,
                )
            phase = "attempt" if "attempt" in self.launches else "context"
            if (
                self.launches
                and args[0] == "exec-out"
                and args[-1] in ("files/context.json", "files/result.json")
            ):
                self.phase_commands.append((phase, now[0], timeout))
            if args[0] == "exec-out" and args[-1] in (
                "files/context.json",
                "files/result.json",
            ):
                self.calls.append(args)
                kind = "context" if args[-1] == "files/context.json" else "result"
                self.reads[kind] += 1
                number = self.reads[kind]
                valid = (
                    context() if kind == "context" else result(cleanup="quarantined")
                )
                if mode == "uid_" + kind + "_read":
                    self.changed = True
                if mode == kind + "_late":
                    now[0] += timeout + 0.01
                    return m.custody.CommandOutcome(0, valid, False, True)
                if mode == kind + "_missing" or (mode == "delayed" and number < 3):
                    return m.custody.CommandOutcome(1, b"", False, True)
                if mode == "progress_only" and kind == "result":
                    valid = result(stage="discover", cleanup="pending")
                if number == 1:
                    if mode == kind + "_stale":
                        valid = (
                            context(generation="b" * 32)
                            if kind == "context"
                            else result(generation="b" * 32)
                        )
                    elif mode == kind + "_partial":
                        valid = b'{"schemaVersion":'
                    elif mode == kind + "_invalid":
                        valid = (
                            context(sourceNetworkType=True)
                            if kind == "context"
                            else result(authenticated=True)
                        )
                return m.custody.CommandOutcome(0, valid, False, True)
            return super().run(
                argv, timeout, max_bytes=max_bytes, input_bytes=input_bytes
            )

    boundary = ReadinessBoundary()
    request = m.PrivateDeviceRequest(
        "inventedprivate", "KR", "a" * 32, budget_millis=1000, greeting_millis=100
    )
    try:
        out = m.run_device_probe(cfg, request, runner=boundary)
        if mode.startswith("uid_"):
            assert out.failure == "package_identity"
            assert out.package_cleanup == "uncertain"
            assert not any(
                c[:3] == ("shell", "am", "force-stop") for c in boundary.calls
            )
            assert not any(c[0] == "uninstall" for c in boundary.calls)
            if mode == "uid_context_read":
                assert not boundary.inputs and not out.device
                assert not (Path(out.private_directory) / "context.json").exists()
                assert not (Path(out.private_directory) / "request.json").exists()
            else:
                assert not out.device
        elif mode in ("context_missing", "context_late"):
            assert out.failure == "context_deadline"
            assert not boundary.inputs and "attempt" not in boundary.launches
            assert now[0] <= boundary.launches["context"] + 5.02
        elif mode in ("result_missing", "result_late", "progress_only"):
            assert out.failure == "helper_deadline"
            assert now[0] <= boundary.launches["attempt"] + 11.02
        else:
            assert out.failure == "none"
            assert out.package_cleanup == "confirmed_absent"
            assert out.staging_cleanup == "removed"
            directory = Path(out.private_directory)
            assert (
                json.loads((directory / "context.json").read_bytes())["generation"]
                == "a" * 32
            )
            assert (directory / "greeting.bin").read_bytes() == bytes(range(64))
            assert out.device["authenticated"] is False
            assert json.loads(boundary.inputs[0])["serial"] == "INVENTEDPRIVATE"
            assert (
                json.loads(boundary.inputs[0])["profile"]["model"]
                == "1234567890abcdef1234567890abcdef"
            )
            if mode == "delayed":
                assert boundary.reads == {"context": 3, "result": 3}
            elif mode.endswith(("stale", "partial", "invalid")):
                assert boundary.reads[mode.split("_")[0]] == 2
        assert "INVENTEDPRIVATE" not in json.dumps(boundary.calls)
        assert "1234567890abcdef1234567890abcdef" not in json.dumps(asdict(out))
        if mode.endswith(("missing", "late")) or mode == "progress_only":
            # Every readiness child gets only the remaining original phase budget.
            for phase, started, timeout in boundary.phase_commands:
                limit = 5 if phase == "context" else 11
                if started < boundary.launches[phase] + limit:
                    assert timeout <= boundary.launches[phase] + limit - started + 1e-8
    finally:
        # Only the test's originally allocated files/directories are removed.
        for directory in cfg.staging_root.iterdir():
            assert directory.parent.resolve() == cfg.staging_root.resolve()
            for item in directory.iterdir():
                assert item.is_file() and not item.is_symlink()
                item.unlink()
            directory.rmdir()
        cfg.staging_root.rmdir()


@pytest.mark.parametrize("mode", ["success", "present", "uid_change", "cleanup_fail"])
def test_controller_private_stage_and_uid_cleanup(tmp_path, monkeypatch, mode):
    import hashlib

    m = api()
    cfg = controller_config(m, tmp_path)
    artifact = tmp_path / "helper.apk"
    artifact.write_bytes(b"invented signed reviewed fixture")
    identity = m.custody._BuildArtifact(
        artifact,
        artifact.stat().st_size,
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    # Independent review boundary is external; real copying and UID guards run here.
    monkeypatch.setattr(m, "_load_reviewed", lambda c: identity)
    boundary = DeviceBoundary(
        m,
        present=mode == "present",
        uid_change=mode == "uid_change",
        cleanup_fail=mode == "cleanup_fail",
    )
    request = m.PrivateDeviceRequest("inventedprivate", "KR", "a" * 32)
    out = m.run_device_probe(cfg, request, runner=boundary)
    assert "INVENTEDPRIVATE" not in json.dumps(boundary.calls)
    if mode == "present":
        assert out.failure == "package_present" and not any(
            c[0] == "install" for c in boundary.calls
        )
        assert not any(c[0] == "uninstall" for c in boundary.calls)
    elif mode == "success":
        assert (
            out.failure == "none"
            and out.package_cleanup == "confirmed_absent"
            and out.staging_cleanup == "removed"
        )
        assert out.device["cleanup"] == "quarantined"
        directory = Path(out.private_directory)
        assert (directory / "greeting.bin").read_bytes() == bytes(range(64))
        assert json.loads(boundary.inputs[0])["serial"] == "INVENTEDPRIVATE"
        assert boundary.uid_reads >= 8
        assert not any(c[:2] == ("shell", "logcat") for c in boundary.calls)
        for name in ("greeting.bin", "request.json", "context.json"):
            (directory / name).unlink()
        directory.rmdir()
    else:
        assert out.package_cleanup == "uncertain"
        assert not any(c[0] == "uninstall" for c in boundary.calls)
        # Deliberately retained uncertainty, then test owns removal of only known files.
        for directory in cfg.staging_root.iterdir():
            for f in directory.iterdir():
                f.unlink()
            directory.rmdir()
    cfg.staging_root.rmdir()


def test_review_rejects_unaccepted_source_before_runtime(tmp_path):
    m = api()
    cfg = controller_config(m, tmp_path)
    cfg.build_result.write_text("{}")
    cfg.review_receipt.write_text(
        json.dumps({"status": "READY_FOR_REVIEW", "files": {}})
    )
    boundary = DeviceBoundary(m)
    out = m.run_device_probe(
        cfg, m.PrivateDeviceRequest("invented", "KR", "a" * 32), runner=boundary
    )
    assert out.failure == "build_invalid" and not boundary.calls
    cfg.staging_root.rmdir()


def test_builder_refuses_author_receipt_without_tool_execution(tmp_path):
    import shutil

    root = Path(__file__).resolve().parents[2]
    fake = tmp_path / "author.json"
    fake.write_text('{"status":"READY_FOR_REVIEW","files":{}}')
    outcome = offline_child(
        (
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(root / "services/tvt-android-helper/build-local-device-probe.ps1"),
            "-ApprovedApk",
            str(tmp_path / "never-open.apk"),
            "-TransportReceipt",
            str(fake),
            "-BootstrapReceipt",
            str(fake),
            "-DiscoveryReceipt",
            str(fake),
        ),
        tmp_path,
        5,
    )
    assert (
        outcome.returncode != 0
        and b"Root-reviewed exact source receipt required" in outcome.stderr
    )
    assert not (tmp_path / "never-open.apk").exists()


def test_reviewed_build_requires_dependency_custody(tmp_path, monkeypatch):
    import hashlib

    m = api()
    fake_root = tmp_path / "repo"
    fake_root.mkdir()
    monkeypatch.setattr(m, "ROOT", fake_root)
    identities = {}
    for relative in m.OWNED:
        p = fake_root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"invented source")
        identities[relative] = {
            "bytes": 15,
            "sha256": hashlib.sha256(b"invented source").hexdigest(),
        }
    cfg = controller_config(m, tmp_path)
    cfg.review_receipt.write_text(
        json.dumps(
            {"status": "ACCEPTED_WINDOWS_LOCAL_DEVICE_ROOT_REVIEW", "files": identities}
        )
    )
    apk = tmp_path / "helper.apk"
    apk.write_bytes(b"invented apk")
    cfg.build_result.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "BUILT_HOST_VERIFIED_DEVICE_NOT_EXECUTED",
                "package": m.PACKAGE,
                "developmentOnly": True,
                "signatureVerified": True,
                "manifestVerified": True,
                "nativeVerified": True,
                "developmentKeyDeleted": True,
                "deviceExecution": "NOT_EXECUTED",
                "sourceHashes": {
                    str(fake_root / p): identities[p]["sha256"] for p in m.OWNED[:3]
                },
                "discoveryReceiptSha256": hashlib.sha256(
                    cfg.review_receipt.read_bytes()
                ).hexdigest(),
                "apk": str(apk),
                "apkBytes": apk.stat().st_size,
                "apkSha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
            }
        )
    )
    with pytest.raises(ValueError, match="dependency maps"):
        m._load_reviewed(cfg)
    dependencies = {}
    for group, paths in (
        ("transport", m.TRANSPORT_PATHS),
        ("bootstrap", m.BOOTSTRAP_PATHS),
    ):
        mapping = {}
        for relative in paths:
            p = fake_root / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"invented reviewed dependency")
            mapping[relative] = {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
        dependencies[group] = mapping
    receipt = json.loads(cfg.review_receipt.read_bytes())
    receipt["dependencies"] = dependencies
    cfg.review_receipt.write_text(json.dumps(receipt))
    build = json.loads(cfg.build_result.read_bytes())
    build["dependencies"] = dependencies
    build["discoveryReceiptSha256"] = hashlib.sha256(
        cfg.review_receipt.read_bytes()
    ).hexdigest()
    build["transportReceiptSha256"] = "a" * 64
    build["bootstrapReceiptSha256"] = "b" * 64
    build["sourceHashes"].update(
        {p: dependencies["transport"][p]["sha256"] for p in m.TRANSPORT_PATHS[:5]}
    )
    cfg.build_result.write_text(json.dumps(build))
    assert m._load_reviewed(cfg).sha256 == hashlib.sha256(b"invented apk").hexdigest()
    (fake_root / m.TRANSPORT_PATHS[0]).write_bytes(b"different source")
    with pytest.raises(ValueError, match="dependency changed"):
        m._load_reviewed(cfg)
    cfg.staging_root.rmdir()


class OwnershipPipe:
    """Inert OS boundary; completion comes only from an explicit natural-release event."""

    def __init__(self, release, *, block=False):
        self.release = release
        self.block = block
        self.closed = False

    def read(self, count):
        if self.block:
            self.release.wait()
        return b""

    def write(self, data):
        if self.block:
            self.release.wait()
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class OwnershipChild:
    def __init__(self, mode):
        import threading

        self.mode = mode
        self.release = threading.Event()
        self.kills = 0
        self.stdout = OwnershipPipe(self.release, block=mode != "unfinished_feed")
        self.stderr = OwnershipPipe(self.release)
        self.stdin = OwnershipPipe(self.release, block=mode == "unfinished_feed")

    def wait(self, timeout=None):
        if self.mode == "unkillable" and not self.release.is_set():
            if timeout is None:
                self.release.wait()
            else:
                raise subprocess.TimeoutExpired("invented-child", timeout)
        return 7 if self.mode == "unkillable" else 0

    def poll(self):
        return (
            None
            if self.mode == "unkillable" and not self.release.is_set()
            else (7 if self.mode == "unkillable" else 0)
        )

    def kill(self):
        self.kills += 1
        raise OSError("invented kill rejection")


@pytest.mark.parametrize("mode", ["unkillable", "unfinished_pipe"])
def test_fix1_default_api_retains_original_owner_and_fences_next_attempt(
    tmp_path, monkeypatch, mode
):
    m = api()
    cfg = controller_config(m, tmp_path)
    child = OwnershipChild(mode)
    spawned = []

    def start(*args, **kwargs):
        spawned.append(args[0])
        return child

    monkeypatch.setattr(m.subprocess, "Popen", start)
    monkeypatch.setattr(m, "_load_reviewed", lambda config: None)
    try:
        first = m.run_device_probe(
            cfg, m.PrivateDeviceRequest("invented", "KR", "a" * 32)
        )
        assert hasattr(m, "_DEFAULT_SUPERVISOR"), (
            "default owner lifetime supervisor missing"
        )
        supervisor = m._DEFAULT_SUPERVISOR
        owners = supervisor.pending_owners()
        assert len(owners) == 1 and owners[0].children[0] is child
        original_receipt = owners[0].receipts[0]
        assert (
            original_receipt["reaped"] is False
            and original_receipt["ownershipRetained"] is True
        )
        second = m.run_device_probe(
            cfg, m.PrivateDeviceRequest("invented", "KR", "b" * 32)
        )
        assert (
            second.failure == "host_owner_pending"
            and second.host_ownership == "retained"
        )
        assert len(spawned) == 1
        assert (
            first.failure in ("child_timeout", "child_unreaped")
            and first.host_ownership == "retained"
        )
        assert child.kills == (1 if mode == "unkillable" else 0)
        child.release.set()
        supervisor.wait_for_ownership()
        assert (
            original_receipt["reaped"] is False
        )  # Original bounded-return observation is immutable.
        assert (
            original_receipt["ownerReaped"] is True
            and original_receipt["ownerPipesCompleted"] is True
        )
        assert not supervisor.pending_owners()
        assert hasattr(m, "wait_for_default_ownership"), (
            "stable default passive completion API missing"
        )
        m.wait_for_default_ownership()

        def reject_build(config):
            raise ValueError("inert independent build gate")

        monkeypatch.setattr(m, "_load_reviewed", reject_build)
        resumed = m.run_device_probe(
            cfg, m.PrivateDeviceRequest("invented", "KR", "c" * 32)
        )
        assert (
            resumed.failure == "build_invalid" and resumed.host_ownership == "confirmed"
        )
        assert len(spawned) == 1
        assert original_receipt is supervisor.receipt_history[-1][0]
        assert child.kills == (1 if mode == "unkillable" else 0)
    finally:
        child.release.set()
        if hasattr(m, "_DEFAULT_SUPERVISOR"):
            m._DEFAULT_SUPERVISOR.wait_for_ownership()
        cfg.staging_root.rmdir()


def test_fix1_unfinished_feed_stays_owned_without_kill_retry(monkeypatch):
    m = api()
    child = OwnershipChild("unfinished_feed")
    monkeypatch.setattr(m.subprocess, "Popen", lambda *args, **kwargs: child)
    runner = m.PrivateRunner()
    try:
        outcome = runner.run(("invented-child",), 0.01, input_bytes=b"INVENTEDPRIVATE")
        assert outcome.reaped is False
        assert hasattr(runner, "wait_for_ownership"), "passive pipe/feed owner missing"
        receipt = runner.receipts[0]
        assert runner.blocked and receipt["ownershipRetained"]
        assert "INVENTEDPRIVATE" not in json.dumps(runner.receipts)
        child.release.set()
        runner.wait_for_ownership()
        assert not runner.blocked and receipt["ownerPipesCompleted"]
        assert child.kills == 0
    finally:
        child.release.set()
        if hasattr(runner, "wait_for_ownership"):
            runner.wait_for_ownership()


@pytest.mark.parametrize("interface", ["cli", "api_exit"])
@pytest.mark.parametrize("mode", ["unkillable", "unfinished_pipe"])
def test_fix1_cli_waits_for_original_owner_before_exit(tmp_path, mode, interface):
    import sys
    import tempfile
    import threading

    staging = Path(
        tempfile.mkdtemp(prefix="device-cli-private-", dir="C:/Windows/Temp")
    )
    marker = tmp_path / "natural-completion"
    receipt = tmp_path / "cli-owner.json"
    adb = tmp_path / "adb.exe"
    adb.write_bytes(b"inert CLI file gate")
    script = tmp_path / "inert-cli.py"
    script.write_text(
        r"""
import importlib.util,sys,time,threading,json,atexit,argparse
from pathlib import Path
spec=importlib.util.spec_from_file_location("inert_contract",sys.argv[1]);t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
m=t.api();child=t.OwnershipChild(sys.argv[2]);marker=Path(sys.argv[3]);receipt=Path(sys.argv[4]);started=[]
def start(*args,**kwargs):started.append(args[0]);return child
m.subprocess.Popen=start;m._load_reviewed=lambda c:None
def complete():
 while not marker.exists():time.sleep(.02)
 child.release.set()
threading.Thread(target=complete,daemon=True).start()
interface=sys.argv[5];sys.argv=["private-cli",*sys.argv[6:]]
def write_receipt():
 records=m._DEFAULT_SUPERVISOR.receipt_history if hasattr(m,"_DEFAULT_SUPERVISOR") else []
 receipt.write_text(json.dumps(dict(code=code,kills=child.kills,commands=len(started),receipts=records)),encoding="utf-8")
if interface=="api_exit":
 parser=argparse.ArgumentParser()
 for name in ("adb","build-result","review-receipt","staging-root","runtime-profile"):parser.add_argument("--"+name,required=True)
 args=parser.parse_args()
 config=m.DeviceProbeConfig(Path(args.adb),Path(args.build_result),Path(args.review_receipt),"development-debug",Path(args.staging_root),args.runtime_profile)
 value=json.loads(sys.stdin.buffer.read())
 result=m.run_device_probe(config,m.PrivateDeviceRequest(**value))
 print(json.dumps(m.asdict(result)),flush=True);code=1
 atexit.register(write_receipt)  # Normal thread shutdown precedes this receipt; no explicit wait.
else:
 code=m.main();write_receipt()
raise SystemExit(code)
""",
        encoding="utf-8",
    )
    argv = (
        sys.executable,
        str(script),
        str(Path(__file__).resolve()),
        mode,
        str(marker),
        str(receipt),
        interface,
        "--adb",
        str(adb),
        "--build-result",
        str(tmp_path / "build.json"),
        "--review-receipt",
        str(tmp_path / "review.json"),
        "--staging-root",
        str(staging),
        "--runtime-profile",
        "google-translation-development",
    )
    started = time.time()
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    payload = json.dumps(
        {
            "serial": "INVENTEDPRIVATE",
            "country_code": "KR",
            "generation": "a" * 32,
            "budget_millis": 1000,
            "greeting_millis": 200,
            "greeting_bytes": 10240,
        }
    ).encode()
    process.stdin.write(payload)
    process.stdin.close()
    output = []

    def read_line():
        output.append(process.stdout.readline())

    reader = threading.Thread(target=read_line, daemon=True)
    reader.start()
    try:
        reader.join(6)
        assert not reader.is_alive(), "CLI did not report bounded uncertainty"
        time.sleep(0.1)
        assert process.poll() is None, (
            "CLI exited while original child/pipe owner remained unresolved"
        )
        safe = json.loads(output[0])
        assert safe["host_ownership"] == "retained"
        assert "INVENTEDPRIVATE" not in output[0].decode()
    finally:
        marker.write_text("natural completion")
        process.wait(timeout=6)
        reader.join(2)
        rest = process.stdout.read()
        errors = process.stderr.read()
        process.stdout.close()
        process.stderr.close()
        record = {
            "argv": list(argv),
            "cwd": str(Path.cwd()),
            "started": started,
            "ended": time.time(),
            "exit": process.returncode,
            "stdout": (b"".join(output) + rest).decode(errors="replace"),
            "stderr": errors.decode(errors="replace"),
            "privateInputRecorded": False,
        }
        (tmp_path / "cli-command.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        staging.rmdir()
    observed = json.loads(receipt.read_bytes())
    assert process.returncode == 1 and observed["commands"] == 1
    assert observed["kills"] == (1 if mode == "unkillable" else 0)
    original = observed["receipts"][0][0]
    assert (
        original["reaped"] is False
        and original["ownerReaped"] is True
        and original["ownerPipesCompleted"] is True
    )


def test_fix1_monitor_start_failure_keeps_current_owner_until_completion(monkeypatch):
    import threading

    m = api()
    child = OwnershipChild("unkillable")
    monkeypatch.setattr(m.subprocess, "Popen", lambda *args, **kwargs: child)
    original_start = threading.Thread.start

    def start(thread):
        if thread.name == "private-child-owner":
            threading.Timer(0.05, child.release.set).start()
            raise RuntimeError("inert ownership thread admission failure")
        return original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", start)
    runner = m.PrivateRunner()
    try:
        outcome = runner.run(("invented-child",), 0.01)
        assert outcome.reaped is False
        receipt = runner.receipts[0]
        assert receipt["ownerThreadStartFailed"] is True
        assert receipt["ownerReaped"] is True and receipt["ownerPipesCompleted"] is True
        assert not runner.blocked and child.kills == 1
        runner.wait_for_ownership()
    finally:
        child.release.set()


def admission_boundary(m, monkeypatch, stream, phase):
    import threading

    child = OwnershipChild("unkillable")
    child.stderr.block = True
    child.stdin.block = True
    original_thread = threading.Thread
    original_start = original_thread.start
    original_join = original_thread.join
    candidates = {}
    began = []

    def factory(*args, **kwargs):
        target = kwargs.get("target")
        label = None
        if target and target.__name__ == "drain":
            label = "stdout" if kwargs["args"][1] else "stderr"
        elif target and target.__name__ == "feed":
            label = "stdin"
        if label == stream and phase == "construct":
            raise RuntimeError("inert worker construction rejection")
        worker = original_thread(*args, **kwargs)
        if label:
            candidates[worker] = label
        return worker

    def start(worker):
        label = candidates.get(worker)
        if label == stream and phase == "start":
            raise OSError("inert worker start rejection")
        original_start(worker)
        if label:
            began.append(label)
        if label == stream and phase == "interrupt":
            raise KeyboardInterrupt()

    def join(worker, *args, **kwargs):
        if worker in candidates:
            assert worker._started.is_set(), "unstarted worker joined"
        return original_join(worker, *args, **kwargs)

    monkeypatch.setattr(m.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(original_thread, "start", start)
    monkeypatch.setattr(original_thread, "join", join)
    monkeypatch.setattr(threading, "Thread", factory)
    return child, began, candidates


@pytest.mark.parametrize("stream", ["stdout", "stderr", "stdin"])
@pytest.mark.parametrize("phase", ["construct", "start", "interrupt"])
def test_fix2_admission_retains_partial_workers_default_fence(
    tmp_path, monkeypatch, stream, phase
):
    m = api()
    cfg = controller_config(m, tmp_path)
    child, began, _candidates = admission_boundary(m, monkeypatch, stream, phase)
    monkeypatch.setattr(m, "_load_reviewed", lambda config: None)
    original_run = m.PrivateRunner.run

    def private_input(self, argv, timeout, **kwargs):
        kwargs["input_bytes"] = b"INVENTEDPRIVATE"
        return original_run(self, argv, timeout, **kwargs)

    monkeypatch.setattr(m.PrivateRunner, "run", private_input)
    try:
        try:
            m.run_device_probe(cfg, m.PrivateDeviceRequest("invented", "KR", "a" * 32))
        except (KeyboardInterrupt, OSError, RuntimeError) as error:
            assert isinstance(error, (KeyboardInterrupt, OSError, RuntimeError))
        owners = m._DEFAULT_SUPERVISOR.pending_owners()
        assert len(owners) == 1, "acquired child obligation lost during I/O setup"
        runner = owners[0]
        assert runner.children[0] is child and len(runner.receipts) == 1
        record = runner.receipts[0]
        assert (
            record["spawned"]
            and record["ownershipRetained"]
            and record["reaped"] is False
        )
        expected = ["stdout", "stderr", "stdin"]
        index = expected.index(stream)
        wanted = expected[: index + (phase == "interrupt")]
        assert record["startedWorkers"] == wanted and began == wanted
        assert len(runner.owners[0][1]) == len(wanted)
        next_result = m.run_device_probe(
            cfg, m.PrivateDeviceRequest("invented", "KR", "b" * 32)
        )
        assert next_result.failure == "host_owner_pending"
        assert child.kills == 1 and "INVENTEDPRIVATE" not in json.dumps(runner.receipts)
        child.release.set()
        m.wait_for_default_ownership()
        assert (
            record["ownerReaped"]
            and record["ownerWorkersCompleted"]
            and record["ownerStreamsReleased"]
        )
        assert record["ownerPipesCompleted"] == (
            phase == "interrupt" and stream == "stdin"
        )
        assert record["ownerUnadmittedStreams"] == [
            n for n in expected if n not in wanted
        ]
        assert all(p.closed for p in (child.stdout, child.stderr, child.stdin))
        assert not m._DEFAULT_SUPERVISOR.pending_owners() and child.kills == 1
    finally:
        child.release.set()
        m.wait_for_default_ownership()
        cfg.staging_root.rmdir()


@pytest.mark.parametrize("stream", ["stdout", "stderr", "stdin"])
@pytest.mark.parametrize("interface", ["api_exit", "cli"])
def test_fix2_setup_failure_preserves_normal_exit(tmp_path, stream, interface):
    import sys
    import tempfile

    staging = Path(tempfile.mkdtemp(prefix="device-admission-", dir="C:/Windows/Temp"))
    attempted = tmp_path / "admission-attempted"
    release = tmp_path / "natural-completion"
    receipt = tmp_path / "owner.json"
    adb = tmp_path / "adb.exe"
    adb.write_bytes(b"inert file gate")
    script = tmp_path / "inert-admission-exit.py"
    script.write_text(
        r"""
import importlib.util,sys,time,threading,json,argparse,atexit
from pathlib import Path
spec=importlib.util.spec_from_file_location("inert_tests",sys.argv[1]);t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
m=t.api();stream=sys.argv[2];interface=sys.argv[3];attempted=Path(sys.argv[4]);release=Path(sys.argv[5]);receipt=Path(sys.argv[6])
child=t.OwnershipChild("unkillable");child.stderr.block=True;child.stdin.block=True
original_thread=threading.Thread;original_start=original_thread.start;candidates={}
def factory(*args,**kwargs):
 target=kwargs.get("target");label=None
 if target and target.__name__=="drain":label="stdout" if kwargs["args"][1] else "stderr"
 elif target and target.__name__=="feed":label="stdin"
 worker=original_thread(*args,**kwargs)
 if label:candidates[worker]=label
 return worker
def start(worker):
 if candidates.get(worker)==stream:attempted.write_text("attempted");raise RuntimeError("inert initial admission rejection")
 return original_start(worker)
m.subprocess.Popen=lambda *args,**kwargs:child;m._load_reviewed=lambda c:None
original_run=m.PrivateRunner.run
def run(self,argv,timeout,**kwargs):kwargs["input_bytes"]=b"INVENTEDPRIVATE";return original_run(self,argv,timeout,**kwargs)
m.PrivateRunner.run=run
original_thread.start=start;threading.Thread=factory
def natural():
 while not release.exists():time.sleep(.02)
 child.release.set()
original_thread(target=natural,daemon=True).start()
sys.argv=["private-cli",*sys.argv[7:]]
def save():receipt.write_text(json.dumps(dict(kills=child.kills,receipts=m._DEFAULT_SUPERVISOR.receipt_history)),encoding="utf-8")
if interface=="api_exit":
 parser=argparse.ArgumentParser()
 for name in ("adb","build-result","review-receipt","staging-root","runtime-profile"):parser.add_argument("--"+name,required=True)
 args=parser.parse_args();cfg=m.DeviceProbeConfig(Path(args.adb),Path(args.build_result),Path(args.review_receipt),"development-debug",Path(args.staging_root),args.runtime_profile)
 try:m.run_device_probe(cfg,m.PrivateDeviceRequest(**json.loads(sys.stdin.buffer.read())))
 except BaseException:pass
 atexit.register(save)
else:
 try:m.main()
 except BaseException:pass
 save()
""",
        encoding="utf-8",
    )
    argv = (
        sys.executable,
        str(script),
        str(Path(__file__).resolve()),
        stream,
        interface,
        str(attempted),
        str(release),
        str(receipt),
        "--adb",
        str(adb),
        "--build-result",
        str(tmp_path / "build.json"),
        "--review-receipt",
        str(tmp_path / "review.json"),
        "--staging-root",
        str(staging),
        "--runtime-profile",
        "google-translation-development",
    )
    started = time.time()
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    process.stdin.write(
        json.dumps(
            {
                "serial": "INVENTEDPRIVATE",
                "country_code": "KR",
                "generation": "a" * 32,
                "budget_millis": 1000,
                "greeting_millis": 200,
                "greeting_bytes": 10240,
            }
        ).encode()
    )
    process.stdin.close()
    try:
        deadline = time.monotonic() + 5
        while not attempted.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert attempted.exists(), "inert worker admission never exercised"
        time.sleep(0.15)
        assert process.poll() is None, (
            "post-spawn setup lost original owner at normal exit"
        )
    finally:
        release.write_text("natural completion")
        process.wait(timeout=5)
        stdout = process.stdout.read()
        stderr = process.stderr.read()
        process.stdout.close()
        process.stderr.close()
        staging.rmdir()
        (tmp_path / "exit-command.json").write_text(
            json.dumps(
                {
                    "argv": list(argv),
                    "cwd": str(Path.cwd()),
                    "started": started,
                    "ended": time.time(),
                    "exit": process.returncode,
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    saved = json.loads(receipt.read_bytes())
    assert saved["kills"] == 1
    record = saved["receipts"][0][0]
    assert record["spawned"] and record["reaped"] is False
    assert (
        record["ownerReaped"]
        and record["ownerStreamsReleased"]
        and record["ownerPipesCompleted"] is False
    )
    assert (
        record["startedWorkers"]
        == ["stdout", "stderr", "stdin"][: ["stdout", "stderr", "stdin"].index(stream)]
    )
    assert "INVENTEDPRIVATE" not in stdout.decode(
        errors="replace"
    ) and "INVENTEDPRIVATE" not in json.dumps(saved)


def test_fix2_interrupted_start_without_proof_remains_fenced(tmp_path, monkeypatch):
    import threading

    m = api()
    cfg = controller_config(m, tmp_path)
    child = OwnershipChild("unkillable")
    child.stderr.block = True
    original_start = threading.Thread.start
    candidate = []

    def start(worker):
        if worker.name == "private-stdout":
            candidate.append(worker)
            raise KeyboardInterrupt()
        return original_start(worker)

    monkeypatch.setattr(threading.Thread, "start", start)
    monkeypatch.setattr(m.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(m, "_load_reviewed", lambda config: None)
    try:
        with pytest.raises(KeyboardInterrupt):
            m.run_device_probe(cfg, m.PrivateDeviceRequest("invented", "KR", "a" * 32))
        owners = m._DEFAULT_SUPERVISOR.pending_owners()
        assert len(owners) == 1
        record = owners[0].receipts[0]
        assert record["startedWorkers"] == [] and record["unknownStartWorkers"] == [
            "stdout"
        ]
        child.release.set()
        time.sleep(0.15)
        assert m._DEFAULT_SUPERVISOR.pending_owners() and "ownerReaped" not in record
        assert (
            m.run_device_probe(
                cfg, m.PrivateDeviceRequest("invented", "KR", "b" * 32)
            ).failure
            == "host_owner_pending"
        )
        # Fixture supplies the first actual start, simulating delayed admission proof.
        # The production owner only observes; it never retries this start.
        original_start(candidate[0])
        m.wait_for_default_ownership()
        assert (
            record["ownerStartedWorkers"] == ["stdout"]
            and record["ownerPipesCompleted"] is False
        )
        assert record["ownerStreamsReleased"] and child.kills == 1
    finally:
        child.release.set()
        if candidate and not candidate[0]._started.is_set():
            original_start(candidate[0])
        m.wait_for_default_ownership()
        cfg.staging_root.rmdir()


def google_localdevice_absence():
    return (
        Path(__file__).resolve().parents[2]
        / ".superpowers/verification/windows-native-root/localdevice-google-absence.stdout"
    ).read_bytes()


def test_fix3_real_google_absence_history_reaches_owned_staging(tmp_path, monkeypatch):
    import hashlib

    m = api()
    cfg = controller_config(m, tmp_path)
    artifact = tmp_path / "helper.apk"
    artifact.write_bytes(b"invented reviewed helper")
    identity = m.custody._BuildArtifact(
        artifact,
        artifact.stat().st_size,
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(m, "_load_reviewed", lambda c: identity)

    class ActualAbsence(DeviceBoundary):
        def run(self, argv, timeout, **kwargs):
            args = argv[7:]
            if args[:3] == ("shell", "dumpsys", "package") and not self.installed:
                self.uid_reads += 1
                self.calls.append(args)
                return m.custody.CommandOutcome(
                    0, google_localdevice_absence(), False, True
                )
            return super().run(argv, timeout, **kwargs)

    boundary = ActualAbsence(m)
    try:
        out = m.run_device_probe(
            cfg, m.PrivateDeviceRequest("invented", "KR", "a" * 32), runner=boundary
        )
        assert out.failure == "none", (
            "legitimate historical package mention blocked owned staging"
        )
        assert (
            any(c[0] == "install" for c in boundary.calls)
            and out.package_cleanup == "confirmed_absent"
        )
        directory = Path(out.private_directory)
        for name in ("context.json", "request.json", "greeting.bin"):
            (directory / name).unlink()
        directory.rmdir()
    finally:
        cfg.staging_root.rmdir()


@pytest.mark.parametrize(
    "change",
    [
        "old_absence",
        "old_header",
        "duplicate_header",
        "wrong_uid",
        "missing_absence",
        "misplaced_history",
        "identity_in_history",
    ],
)
def test_fix3_history_exemption_never_creates_wrong_identity(change):
    m = api()
    raw = google_localdevice_absence()
    if change == "old_absence":
        raw = raw.replace(
            b"Unable to find package: com.wso.tvt.localdevice",
            b"Unable to find package: com.wso.tvt.localprobe",
        )
    elif change == "old_header":
        raw += b"Packages:\n  Package [com.wso.tvt.localprobe] (a):\n    userId=12345\n"
    elif change == "duplicate_header":
        raw += b"Packages:\n  Package [com.wso.tvt.localdevice] (a):\n    userId=12345\n  Package [com.wso.tvt.localprobe] (b):\n    userId=12346\n"
    elif change == "wrong_uid":
        raw += b"    userId=12345\n"
    elif change == "missing_absence":
        raw = raw.replace(b"  Unable to find package: com.wso.tvt.localdevice", b"", 1)
    elif change == "misplaced_history":
        raw = raw.replace(b"Package Changes:", b"Unexpected Section:")
    else:
        raw = raw.replace(
            b"seq=362, package=com.wso.tvt.localprobe",
            b"Package [com.wso.tvt.localprobe] (a):",
        )
    assert hasattr(m, "parse_local_device_uid"), "new scoped package adapter missing"
    with pytest.raises(ValueError):
        m.parse_local_device_uid(raw)


def test_fix3_owned_uid_and_exact_history_adapter():
    m = api()
    assert hasattr(m, "parse_local_device_uid"), "new scoped package adapter missing"
    assert m.parse_local_device_uid(google_localdevice_absence()) is None
    present = b"Package Changes:\n    seq=362, package=com.wso.tvt.localprobe\nPackages:\n  Package [com.wso.tvt.localdevice] (a):\n    userId=12345\n"
    assert m.parse_local_device_uid(present) == 12345
    with pytest.raises(ValueError):
        m.parse_local_device_uid(
            present.replace(b"userId=12345", b"userId=12345\n    userId=12346")
        )
    with pytest.raises(ValueError):
        m.parse_local_device_uid(
            present.replace(
                b"    seq=362, package=com.wso.tvt.localprobe",
                b"    seq=362, package=com.wso.tvt.localprobe.extra",
            )
        )
