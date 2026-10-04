package com.wso.tvt.local;

import android.app.Activity;
import android.os.Bundle;
import android.os.Process;
import android.os.SystemClock;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** A private operator, one generation, one discover/open. No login or send path. */
public final class LocalDeviceProbeActivity extends Activity {
    private static boolean attempted;
    private final Object outputLock = new Object();
    private volatile boolean closed;
    private String generation, stage="validated", failure="none", cleanup="not_started";
    private int deviceType, nativeError, greetingBytes;
    private boolean transportOpen;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        final String phase=getIntent().getStringExtra("phase");
        generation=getIntent().getStringExtra("generation");
        if (generation==null || !generation.matches("[a-f0-9]{32}")) { finish(); return; }
        if ("context".equals(phase)) {
            try { context(); } catch (Throwable ignored) { /* missing context is a host failure */ }
            finish(); return;
        }
        if (!"attempt".equals(phase)) { finish(); return; }
        synchronized(LocalDeviceProbeActivity.class) {
            if(attempted) { finish(); return; }
            attempted=true;
        }
        new Thread(() -> attempt(), "private-local-device").start();
    }

    private void context() throws IOException {
        String path=getFilesDir().getCanonicalPath();
        if (!ownedPath(path)) throw new IOException();
        String id=singleId(getFilesDir());
        int network=sourceNetworkType((ConnectivityManager)getSystemService(CONNECTIVITY_SERVICE));
        write("context.json",("{\"schemaVersion\":1,\"version\":\"local-device-1\",\"generation\":\""+generation+
            "\",\"privateFilesPath\":\""+path+"\",\"singleId\":\""+id+"\",\"sourceNetworkType\":"+network+"}").getBytes(StandardCharsets.UTF_8));
    }
    static boolean ownedPath(String path) {
        return path.equals("/data/user/0/com.wso.tvt.localdevice/files") || path.equals("/data/data/com.wso.tvt.localdevice/files");
    }
    static String singleId(File files) throws IOException {
        File path=new File(files,"SINGLE_ID");
        String id;
        if(path.exists()) id=new String(read(path,64),StandardCharsets.UTF_8).replace("-","");
        else {
            id=UUID.randomUUID().toString().replace("-","");
            try(FileOutputStream out=new FileOutputStream(path)) { out.write(id.getBytes(StandardCharsets.US_ASCII)); out.getFD().sync(); }
        }
        if(!id.matches("[a-fA-F0-9]{32}")) throw new IOException();
        return id;
    }
    static int sourceNetworkType(ConnectivityManager manager) {
        if(manager==null) return 0;
        NetworkInfo ethernet=manager.getNetworkInfo(9);
        if(ethernet!=null && (ethernet.getState()==NetworkInfo.State.CONNECTED || ethernet.getState()==NetworkInfo.State.CONNECTING)) return 5;
        NetworkInfo active=manager.getActiveNetworkInfo();
        if(active==null || !active.isAvailable()) return 0;
        return networkMapping(active.getType(),active.getSubtype(),active.getSubtypeName());
    }
    static int networkMapping(int type,int subtype,String name) {
        if(type==1) return 4;
        if(type!=0) return 0;
        switch(subtype) {
            case 1: case 2: case 4: case 7: case 11: case 16: return 2;
            case 3: case 5: case 6: case 8: case 9: case 10: case 12: case 14: case 15: case 17:
            case 13: case 18: case 20: return 3;
            default: return "TD-SCDMA".equalsIgnoreCase(name) || "WCDMA".equalsIgnoreCase(name) || "CDMA2000".equalsIgnoreCase(name) ? 3 : 0;
        }
    }

    private void attempt() {
        LocalSerialTransport transport=null;
        try {
            Map<String,Object> request=parse(read(new File(getFilesDir(),"request.json"),4096));
            Map<String,Object> context=parse(read(new File(getFilesDir(),"context.json"),4096));
            LocalSerialConfig config=admit(request,context,generation);
            if(!getFilesDir().getCanonicalPath().equals(context.get("privateFilesPath")) ||
                !singleId(getFilesDir()).equals(context.get("singleId")) ||
                sourceNetworkType((ConnectivityManager)getSystemService(CONNECTIVITY_SERVICE))!=number(context,"sourceNetworkType")) throw new IllegalArgumentException();
            final long hardDeadline=SystemClock.elapsedRealtime()+number(request,"budgetMillis")+5000;
            Thread watchdog=new Thread(() -> {
                while(!closed && SystemClock.elapsedRealtime()<hardDeadline) {
                    try { Thread.sleep(Math.min(100,Math.max(1,hardDeadline-SystemClock.elapsedRealtime()))); }
                    catch(InterruptedException ignored) { /* deadline remains authoritative */ }
                }
                if(!closed) {
                    try {
                        // Best-effort receipt must never delay self termination on a blocked file/lock.
                        Thread receipt=new Thread(() -> {
                            synchronized(outputLock) {
                                stage="deadline"; failure="deadline"; cleanup="pending";
                                try { persist(); } catch(IOException ignored) { }
                            }
                        },"private-deadline-receipt");
                        receipt.setDaemon(true); receipt.start();
                    } finally {
                        // Native calls and cleanup may be stuck. Only this process is owned.
                        Process.killProcess(Process.myPid());
                    }
                }

            },"private-native-deadline");
            watchdog.setDaemon(true); watchdog.start();
            cleanup="pending"; enter("bootstrap");
            transport=new LocalSerialTransport(JniLocalSerialDriver.createAndroid(),config);
            cleanup="pending"; enter("discover");
            deviceType=transport.discover(); nativeError=transport.lastNativeError();
            if(deviceType!=3 && deviceType!=10001 && deviceType!=20001) { failure="unsupported"; return; }
            if(transport.state()!=LocalSerialTransport.State.DISCOVERED) { failure="runtime"; return; }
            enter("open");
            int opened=transport.openTransport();
            if(opened!=0 || transport.state()!=LocalSerialTransport.State.OPEN) { failure="open_failed"; return; }
            transportOpen=true; enter("greeting");
            int cap=number(request,"greetingBytes");
            long stop=SystemClock.elapsedRealtime()+number(request,"greetingMillis");
            try(FileOutputStream out=new FileOutputStream(new File(getFilesDir(),"greeting.bin"),false)) {
                while(SystemClock.elapsedRealtime()<stop && greetingBytes<cap && transport.state()==LocalSerialTransport.State.OPEN) {
                    if(transport.receiveMode()==LocalSerialTransport.ReceiveMode.POLL) {
                        byte[] buffer=new byte[Math.min(10240,cap-greetingBytes)];
                        if(transport.receive(buffer,buffer.length)<0) { failure="receive_failed"; break; }
                    }
                    LocalSerialTransport.Event event;
                    while((event=transport.pollEvent())!=null) {
                        if(event.kind()==LocalSerialTransport.Event.Kind.DATA) {
                            byte[] bytes=event.bytes(); int keep=Math.min(bytes.length,cap-greetingBytes);
                            if(keep>0) { out.write(bytes,0,keep); greetingBytes+=keep; }
                            Arrays.fill(bytes,(byte)0);
                        }
                    }
                    if(greetingBytes<cap) Thread.sleep(10);
                }
                out.getFD().sync();
            }
            if(transport.state()!=LocalSerialTransport.State.OPEN && failure.equals("none")) failure="receive_failed";
        } catch(Throwable error) {
            failure=error instanceof LinkageError ? "linkage" : error instanceof IOException ? "io" :
                error instanceof IllegalArgumentException ? "invalid" : "runtime";
        } finally {
            try {
                enter("cleanup");
                if(transport!=null) {
                    transport.close();
                    cleanup=transport.state()==LocalSerialTransport.State.CLOSED ? "closed" :
                        transport.state()==LocalSerialTransport.State.QUARANTINED ? "quarantined" : "pending";
                } else cleanup="quarantined"; // Bootstrap may have allocated native global state.
                if(!cleanup.equals("pending")) { enter("complete"); closed=cleanup.equals("closed"); }
            } catch(Throwable ignored) { cleanup="pending"; try { persist(); } catch(IOException ignoredIo) { } }
        }
    }

    @SuppressWarnings("unchecked")
    static LocalSerialConfig admit(Map<String,Object> request,Map<String,Object> context,String generation) {
        exact(request,"schemaVersion","version","generation","serial","countryCode","budgetMillis","greetingMillis","greetingBytes","profile");
        exact(context,"schemaVersion","version","generation","privateFilesPath","singleId","sourceNetworkType");
        if(number(request,"schemaVersion")!=1 || number(context,"schemaVersion")!=1 ||
            !"local-device-1".equals(request.get("version")) || !"local-device-1".equals(context.get("version")) ||
            !generation.matches("[a-f0-9]{32}") || !generation.equals(request.get("generation")) || !generation.equals(context.get("generation"))) throw new IllegalArgumentException();
        int budget=number(request,"budgetMillis"),greeting=number(request,"greetingMillis"),cap=number(request,"greetingBytes");
        if(budget<1000 || budget>120000 || greeting<1 || greeting>5000 || greeting>=budget || cap<1 || cap>10240) throw new IllegalArgumentException();
        String country=text(request,"countryCode");
        if(!country.matches("(?:[A-Z]{2})?") || country.equals("AP") || country.equals("EU")) throw new IllegalArgumentException();
        Object raw=request.get("profile"); if(!(raw instanceof Map)) throw new IllegalArgumentException();
        Map<String,Object> p=(Map<String,Object>)raw;
        exact(p,"nat1Host","nat1Port","nat2Host","nat2Port","networkFlag","traversalMode","disableUPnP","privateFilesPath","platform","appVersion","appName","model");
        int network=number(context,"sourceNetworkType");
        if(network!=0 && network!=2 && network!=3 && network!=4 && network!=5) throw new IllegalArgumentException();
        String path=text(context,"privateFilesPath"),id=text(context,"singleId");
        if(!ownedPath(path) || !id.matches("[a-fA-F0-9]{32}") || !path.equals(p.get("privateFilesPath")) || !id.equals(p.get("model")) ||
            !"AND".equals(p.get("platform")) || !"1.18.1.20267".equals(p.get("appVersion")) || !"AND_M_PH_SuperLivePlus".equals(p.get("appName")) ||
            !"c2.autonat.com".equals(p.get("nat1Host")) || number(p,"nat1Port")!=40002 || number(p,"nat2Port")!=7968 ||
            number(p,"networkFlag")!=(network==4?1:0) || number(p,"traversalMode")!=0 || !Boolean.FALSE.equals(p.get("disableUPnP"))) throw new IllegalArgumentException();
        String nat2=text(p,"nat2Host");
        if(!nat2.equals(regionNat2(country)) || !nat2.matches("cli-nat20\\.(autonat\\.us|autonat\\.cn|autonatru\\.com|autonateu\\.com|autonatap\\.com|autonatglb\\.com)")) throw new IllegalArgumentException();
        return LocalSerialConfig.operatorReviewed(text(request,"serial"),text(p,"nat1Host"),number(p,"nat1Port"),nat2,number(p,"nat2Port"),
            number(p,"networkFlag"),0,false,path,"AND","1.18.1.20267","AND_M_PH_SuperLivePlus",id,10240,64,65536,budget*1000000L);
    }
    static String regionNat2(String country) {
        if(Arrays.asList("US").contains(country)) return "cli-nat20.autonat.us";
        if(Arrays.asList("CN").contains(country)) return "cli-nat20.autonat.cn";
        if(Arrays.asList("RU").contains(country)) return "cli-nat20.autonatru.com";
        if(Arrays.asList("BY","BG","CZ","HU","PL","MD","RO","SK","UA","AX","GG","JE","DK","EE","FO","FI","IS","IE","IM","LV","LT","NO","SJ","SE","GB","AL","AD","BA","HR","GI","GR","VA","IT","MT","ME","MK","PT","SM","RS","SI","ES","AT","BE","FR","DE","LI","LU","MC","NL","CH").contains(country)) return "cli-nat20.autonateu.com";
        if(Arrays.asList("AQ","KZ","KG","TJ","TM","UZ","HK","MO","KP","JP","MN","KR","BN","KH","ID","LA","MY","MM","PH","SG","TH","TL","VN","AF","BD","BT","IN","IR","MV","NP","PK","LK","AM","AZ","BH","CY","GE","IQ","IL","JO","KW","LB","OM","QA","SA","PS","SY","TR","AE","YE","AU","CX","CC","HM","NZ","NF","FJ","NC","PG","SB","VU","GU","KI","MH","FM","NR","MP","PW","UM","AS","CK","PF","NU","PN","WS","TK","TO","TV","WF").contains(country)) return "cli-nat20.autonatap.com";
        if(Arrays.asList("DZ","EG","LY","MA","SD","TN","EH","IO","BI","KM","DJ","ER","ET","TF","KE","MG","MW","MU","YT","MZ","RE","RW","SC","SO","SS","UG","TZ","ZM","ZW","AO","CM","CF","TD","CG","CD","GQ","GA","ST","BW","SZ","LS","NA","ZA","BJ","BF","CV","CI","GM","GH","GN","GW","LR","ML","MR","NE","NG","SH","SN","SL","TG","AI","AG","AW","BS","BB","BQ","VG","KY","CU","CW","DM","DO","GD","GP","HT","JM","MQ","MS","PR","BL","KN","LC","MF","VC","SX","TT","TC","VI","BZ","CR","SV","GT","HN","MX","NI","PA","AR","BO","BV","BR","CL","CO","EC","FK","GF","GY","PY","PE","GS","SR","UY","VE","BM","CA","GL","PM").contains(country)) return "cli-nat20.autonatglb.com";
        return "cli-nat20.autonatglb.com";
    }
    static void exact(Map<String,Object> value,String... keys) {
        if(!value.keySet().equals(new HashSet<String>(Arrays.asList(keys)))) throw new IllegalArgumentException();
    }
    static String text(Map<String,Object> map,String key) {
        Object v=map.get(key); if(!(v instanceof String)) throw new IllegalArgumentException(); return (String)v;
    }
    static int number(Map<String,Object> map,String key) {
        Object v=map.get(key); if(!(v instanceof Integer)) throw new IllegalArgumentException(); return (Integer)v;
    }
    private void enter(String value) throws IOException { synchronized(outputLock) { stage=value; persist(); } }
    private void persist() throws IOException {
        String json="{\"schemaVersion\":1,\"version\":\"local-device-1\",\"generation\":\""+generation+
            "\",\"stage\":\""+stage+"\",\"failure\":\""+failure+"\",\"deviceType\":"+deviceType+
            ",\"nativeError\":"+nativeError+",\"transportOpen\":"+transportOpen+",\"greetingBytes\":"+greetingBytes+
            ",\"cleanup\":\""+cleanup+"\",\"authenticated\":false,\"live\":false}";
        write("result.json",json.getBytes(StandardCharsets.UTF_8));
    }
    private void write(String name,byte[] data) throws IOException {
        if(data.length>4096) throw new IOException();
        File tmp=new File(getFilesDir(),name+".tmp");
        try(FileOutputStream out=new FileOutputStream(tmp,false)) { out.write(data); out.getFD().sync(); }
        try { android.system.Os.rename(tmp.getAbsolutePath(),new File(getFilesDir(),name).getAbsolutePath()); }
        catch(android.system.ErrnoException ignored) { throw new IOException(); }
    }
    static byte[] read(File file,int cap) throws IOException {
        if(!file.isFile() || file.length()<1 || file.length()>cap) throw new IOException();
        try(FileInputStream in=new FileInputStream(file); ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            byte[] b=new byte[Math.min(cap,1024)]; int n;
            while((n=in.read(b))!=-1) { if(out.size()+n>cap) throw new IOException(); out.write(b,0,n); }
            return out.toByteArray();
        }
    }
    static Map<String,Object> parse(byte[] raw) {
        if(raw.length<1 || raw.length>4096) throw new IllegalArgumentException();
        Parser p=new Parser(new String(raw,StandardCharsets.UTF_8)); Map<String,Object> result=p.object(); p.space();
        if(p.i!=p.s.length()) throw new IllegalArgumentException(); return result;
    }
    /** Exact object/string/integer/boolean grammar; duplicate keys and arrays rejected. */
    private static final class Parser {
        final String s; int i;
        Parser(String v) { s=v; }
        void space() { while(i<s.length() && " \n\r\t".indexOf(s.charAt(i))>=0) i++; }
        boolean take(char c) { space(); if(i<s.length() && s.charAt(i)==c) { i++; return true; } return false; }
        void need(char c) { if(!take(c)) throw new IllegalArgumentException(); }
        Map<String,Object> object() {
            need('{'); Map<String,Object> m=new HashMap<>(); if(take('}')) return m;
            do { String key=string(); need(':'); Object value=value(); if(m.put(key,value)!=null) throw new IllegalArgumentException(); } while(take(','));
            need('}'); return m;
        }
        Object value() {
            space(); if(i>=s.length()) throw new IllegalArgumentException(); char c=s.charAt(i);
            if(c=='{') return object(); if(c=='"') return string();
            if(s.startsWith("true",i)) { i+=4; return Boolean.TRUE; }
            if(s.startsWith("false",i)) { i+=5; return Boolean.FALSE; }
            int start=i; if(c=='-') i++;
            while(i<s.length() && s.charAt(i)>='0' && s.charAt(i)<='9') i++;
            String n=s.substring(start,i); if(!n.matches("-?(0|[1-9][0-9]*)")) throw new IllegalArgumentException();
            try { return Integer.valueOf(n); } catch(NumberFormatException ignored) { throw new IllegalArgumentException(); }
        }
        String string() {
            need('"'); StringBuilder b=new StringBuilder();
            while(i<s.length()) {
                char c=s.charAt(i++); if(c=='"') return b.toString(); if(c<32) throw new IllegalArgumentException();
                if(c=='\\') {
                    if(i>=s.length()) throw new IllegalArgumentException(); c=s.charAt(i++);
                    switch(c) {
                        case '"': case '\\': case '/': break;
                        case 'b': c='\b'; break; case 'f': c='\f'; break; case 'n': c='\n'; break;
                        case 'r': c='\r'; break; case 't': c='\t'; break;
                        case 'u': if(i+4>s.length() || !s.substring(i,i+4).matches("[a-fA-F0-9]{4}")) throw new IllegalArgumentException(); c=(char)Integer.parseInt(s.substring(i,i+4),16); i+=4; break;
                        default: throw new IllegalArgumentException();
                    }
                }
                b.append(c);
            }
            throw new IllegalArgumentException();
        }
    }
}
