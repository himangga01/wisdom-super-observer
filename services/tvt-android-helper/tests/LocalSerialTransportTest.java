package com.wso.tvt.local;
import com.tvt.network.NatTraveral;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/** Invented inputs only; no Android, network or vendor library execution. */
public final class LocalSerialTransportTest {
    private static int checks;
    private static final AtomicLong IDS = new AtomicLong(10);
    private static void check(boolean b, String message) { checks++; if (!b) throw new AssertionError(message); }
    private static void rejects(Runnable r) {
        try { r.run(); } catch (IllegalArgumentException | IllegalStateException expected) { checks++; return; }
        throw new AssertionError("Expected admission/lifecycle rejection");
    }
    private static LocalSerialConfig config(String sn, String host, String path, int port) {
        return LocalSerialConfig.operatorReviewed(sn,"nat1.invalid",port,host,9998,0,0,true,path,
            "AND","synthetic.1","Fixture","FixtureModel",10240,4,20480,TimeUnit.SECONDS.toNanos(30));
    }
    private static LocalSerialConfig config() { return config("sn123","nat2.invalid","/data/user/0/fixture/files",80); }
    private static LocalSerialConfig profile(String nat1,String platform,String version,String app,String model) {
        return LocalSerialConfig.operatorReviewed("SN",nat1,80,"nat2.invalid",9998,0,0,true,"/private/files",
            platform,version,app,model,10240,4,20480,TimeUnit.SECONDS.toNanos(30));
    }
    private static String repeat(String s,int n) { StringBuilder b=new StringBuilder(); for(int i=0;i<n;i++)b.append(s);return b.toString(); }
    private static void bounds() {
        check(config().serial().equals("SN123"),"ASCII uppercase raw SN");
        config(repeat("A",63),repeat("x",63),"/a",65535);
        rejects(()->config(repeat("A",64),"n","/a",80));
        rejects(()->config("SN",repeat("한",22),"/a",80));
        rejects(()->config("SN","n\u0000x","/a",80)); rejects(()->config("SN","\ud800","/a",80));
        rejects(()->config("SN","n","relative",80)); rejects(()->config("SN","n","/a/../b",80));
        rejects(()->config("SN","n","/"+repeat("p",253),80));
        rejects(()->config("SN","n","/a",0)); rejects(()->config("SN","n","/a",65536));
        rejects(()->config("한","n","/a",80));
        profile(repeat("x",127),repeat("p",31),repeat("v",63),repeat("a",63),repeat("m",63));
        rejects(()->profile(repeat("x",128),"AND","v","a","m"));
        rejects(()->profile("n",repeat("p",32),"v","a","m"));
        rejects(()->profile("n","AND",repeat("v",64),"a","m"));
        rejects(()->profile("n","AND","v",repeat("a",64),"m"));
        rejects(()->profile("n","AND","v","a",repeat("m",64)));
        rejects(()->profile("n","AND","v","a","\udc00"));
        rejects(()->profile("","AND","v","a","m"));
    }
    private static void ordinary() {
        FakeDriver d=new FakeDriver(); LocalSerialTransport t=new LocalSerialTransport(d,config());
        rejects(()->new LocalSerialTransport(new FakeDriver(),config()));
        check(t.discover()==20001 && t.state()==LocalSerialTransport.State.DISCOVERED,"discovery separate from open");
        check(d.serial.equals("SN123"),"no prehash");
        check(t.openTransport()==0 && t.state()==LocalSerialTransport.State.OPEN,"transport open only");
        check(t.receiveMode()==LocalSerialTransport.ReceiveMode.CALLBACK,"numeric three callback receive");
        byte[] data={1,2,3};check(d.callbacks.data(d.id,data)==3,"callback admitted");data[0]=9;
        check(t.pollEvent().bytes()[0]==1,"callback bytes copied");
        check(d.callbacks.data(d.id+1,data)==0,"wrong echo rejected");
        check(d.callbacks.data(d.id,new byte[10241])==0,"oversized callback rejected");
        rejects(()->t.send(new byte[4],0));rejects(()->t.send(new byte[4],5));rejects(()->t.send(new byte[10241],1));
        d.sendResult=2;check(t.send(new byte[3],3)==2,"partial send preserved");
        d.sendResult=4;rejects(()->t.send(new byte[3],3));t.close();
        check(t.state()==LocalSerialTransport.State.CLOSED,"proved synthetic cleanup");
        check(d.order.equals("remove,interrupt,destroy"),"remove callbacks before cleanup");
        check(d.callbacks.data(d.id,data)==0,"late callback rejected");t.close();check(d.destroyCalls==1,"close idempotent");
    }
    private static void polling() {
        FakeDriver d=new FakeDriver();d.connectType=2;LocalSerialTransport t=new LocalSerialTransport(d,config());
        t.discover();t.openTransport();check(t.receiveMode()==LocalSerialTransport.ReceiveMode.POLL,"nonthree poll");
        check(d.callbacks.data(d.id,new byte[1])==0,"poll ignores callbacks");
        check(t.receive(new byte[10240],10240)==0,"zero receive is no data");
        d.recvResult=4;check(t.receive(new byte[4],4)==4 && t.pollEvent().bytes().length==4,"actual buffer cap");
        rejects(()->t.receive(new byte[3],4));rejects(()->t.receive(new byte[10241],1));
        d.recvResult=-1;check(t.receive(new byte[4],4)==-1,"negative receive preserved");
        check(t.state()==LocalSerialTransport.State.FAILED,"failure not auth label");t.close();
        FakeDriver e=new FakeDriver();e.connectType=2;LocalSerialTransport u=new LocalSerialTransport(e,config());u.discover();u.openTransport();
        e.recvResult=5;rejects(()->u.receive(new byte[4],4));check(u.state()==LocalSerialTransport.State.FAILED,"oversized native receive fails closed");u.close();
    }
    private static void queue() {
        FakeDriver d=new FakeDriver();LocalSerialTransport t=new LocalSerialTransport(d,config());t.discover();t.openTransport();
        d.callbacks.connection(d.id,true,20001,"discard detail");
        check(t.state()==LocalSerialTransport.State.OPEN && t.pollEvent().kind()==LocalSerialTransport.Event.Kind.CONNECTION,"status not authentication");
        check(d.callbacks.data(d.id,new byte[10240])==10240,"callback maximum");
        check(d.callbacks.data(d.id,new byte[10240])==10240,"queue exact byte maximum");
        check(d.callbacks.data(d.id,new byte[1])==0 && t.state()==LocalSerialTransport.State.FAILED,"queue overflow fails closed");t.close();
        FakeDriver e=new FakeDriver();LocalSerialTransport u=new LocalSerialTransport(e,config());u.discover();
        for(int i=0;i<5;i++)e.callbacks.connection(e.id,true,20001,"");
        check(u.state()==LocalSerialTransport.State.FAILED,"event count bounded");u.close();
    }
    private static void failures() {
        for(int type:new int[]{0,-1,9,10,40000}) {
            FakeDriver d=new FakeDriver();d.type=type;LocalSerialTransport t=new LocalSerialTransport(d,config());
            check(t.discover()==type && t.lastNativeError()==77,"unsupported/error private result");rejects(t::openTransport);t.close();
        }
        FakeDriver d=new FakeDriver();d.id=0;LocalSerialTransport t=new LocalSerialTransport(d,config());rejects(t::discover);t.close();
        FakeDriver e=new FakeDriver();e.id=-50;LocalSerialTransport u=new LocalSerialTransport(e,config());check(u.discover()==20001,"nonzero signed handle");u.close();
        FakeDriver f=new FakeDriver();f.openResult=8;LocalSerialTransport v=new LocalSerialTransport(f,config());v.discover();
        check(v.openTransport()==8 && v.state()==LocalSerialTransport.State.FAILED,"nonzero open fails");v.close();
    }
    private static final class Worker {
        final FutureTask<Void> result;
        final Thread thread;
        Worker(Runnable action) { result=new FutureTask<>(action,null);thread=new Thread(result);thread.start(); }
    }
    private static void join(Worker worker) {
        try {
            worker.thread.join(3000);check(!worker.thread.isAlive(),"no callback monitor deadlock");
            worker.result.get();
        } catch(InterruptedException failure) {
            Thread.currentThread().interrupt();throw new AssertionError(failure);
        } catch(ExecutionException failure) {
            Throwable cause=failure.getCause();
            if(cause instanceof Error)throw (Error)cause;
            if(cause instanceof RuntimeException)throw (RuntimeException)cause;
            throw new AssertionError(cause);
        }
    }
    private static void await(CountDownLatch l) { try {if(!l.await(3,TimeUnit.SECONDS))throw new AssertionError("latch timeout");}catch(InterruptedException e){throw new AssertionError(e);} }
    private static void reentryAndRace() throws Exception {
        FakeDriver d=new FakeDriver();LocalSerialTransport t=new LocalSerialTransport(d,config());
        d.duringDiscover=()->{Worker callback=new Worker(()->d.callbacks.connection(d.id,true,20001,""));join(callback);t.close();};
        rejects(t::discover);check(t.state()==LocalSerialTransport.State.CLOSED && d.destroyCalls==1,"synchronous close reentry drains");
        FakeDriver e=new FakeDriver();LocalSerialTransport u=new LocalSerialTransport(e,config());
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        e.duringDiscover=()->{entered.countDown();await(release);};
        Worker worker=new Worker(()->rejects(u::discover));check(entered.await(2,TimeUnit.SECONDS),"blocking discovery entered");
        u.close();check(e.destroyCalls==0 && e.interruptCalls==1,"interrupt but retain in flight");
        release.countDown();join(worker);check(e.destroyCalls==1 && u.state()==LocalSerialTransport.State.CLOSED,"destroy after drain");
    }
    private static void reusedEcho() {
        FakeDriver d=new FakeDriver();LocalSerialTransport t=new LocalSerialTransport(d,config());t.discover();LocalSerialDriver.Callbacks old=d.callbacks;t.close();
        FakeDriver e=new FakeDriver();LocalSerialTransport u=new LocalSerialTransport(e,config());u.discover();
        check(old.data(d.id,new byte[1])==0 && u.pollEvent()==null,"retired generation cannot feed next session");u.close();
        FakeDriver f=new FakeDriver();f.id=d.id;LocalSerialTransport v=new LocalSerialTransport(f,config());rejects(v::discover);
        check(v.state()==LocalSerialTransport.State.QUARANTINED,"recycled echo refused");rejects(()->new LocalSerialTransport(new FakeDriver(),config()));
    }
    private static void quarantine() {
        FakeDriver d=new FakeDriver();d.destroyProved=false;LocalSerialTransport t=new LocalSerialTransport(d,config());t.discover();t.close();
        check(t.state()==LocalSerialTransport.State.QUARANTINED,"unproved cleanup quarantine");
        rejects(()->new LocalSerialTransport(new FakeDriver(),config()));t.close();check(d.destroyCalls==1,"uncertain resource never retried");
    }
    private static void bindingClose() {
        FakeDriver d=new FakeDriver();LocalSerialTransport t=new LocalSerialTransport(d,config());
        d.duringBind=t::close;rejects(t::discover);
        check(!d.registered,"close during callback binding removes late registration");
        check(t.state()==LocalSerialTransport.State.CLOSED,"binding race clean closure");
    }
    private static void deadline() {
        LocalSerialConfig c=LocalSerialConfig.operatorReviewed("SN1","n1",80,"n2",9998,0,0,true,
            "/private/files","AND","1.1","Fixture","Model",10240,4,20480,1);
        FakeDriver d=new FakeDriver();LocalSerialTransport t=new LocalSerialTransport(d,c);
        rejects(t::discover);check(t.state()==LocalSerialTransport.State.CLOSED && d.allocateCalls==0,"expired caller budget never enters JNI");
    }
    private static void openingData() {
        FakeDriver d=new FakeDriver();LocalSerialTransport t=new LocalSerialTransport(d,config());t.discover();
        d.duringOpen=()->check(d.callbacks.data(d.id,new byte[]{4,5})==2,"opening synchronous greeting retained");
        t.openTransport();check(t.pollEvent().bytes()[0]==4,"opening data reaches bounded private event");t.close();
        FakeDriver e=new FakeDriver();e.connectType=2;LocalSerialTransport u=new LocalSerialTransport(e,config());u.discover();
        e.duringOpen=()->check(e.callbacks.data(e.id,new byte[]{6})==1,"bounded pending callback before numeric mode");
        u.openTransport();check(u.pollEvent()==null,"poll mode drops pending callback bytes");u.close();
    }
    private static void removalFailure() {
        FakeDriver d=new FakeDriver();d.removalFails=true;LocalSerialTransport t=new LocalSerialTransport(d,config());t.discover();t.close();
        check(d.destroyCalls==0 && t.state()==LocalSerialTransport.State.QUARANTINED,"unremoved callbacks block native destroy");
        rejects(()->new LocalSerialTransport(new FakeDriver(),config()));
    }
    private static void allocationUncertainty() {
        FakeDriver d=new FakeDriver();d.allocationFails=true;LocalSerialTransport t=new LocalSerialTransport(d,config());rejects(t::discover);t.close();
        check(t.state()==LocalSerialTransport.State.QUARANTINED,"unknown allocation outcome retains process");
        rejects(()->new LocalSerialTransport(new FakeDriver(),config()));
    }
    private static void ioFailure() {
        FakeDriver d=new FakeDriver();LocalSerialTransport t=new LocalSerialTransport(d,config());t.discover();t.openTransport();d.sendFails=true;
        rejects(()->t.send(new byte[1],1));check(t.state()==LocalSerialTransport.State.FAILED,"send exception fails transport");t.close();
        FakeDriver e=new FakeDriver();e.connectType=2;LocalSerialTransport u=new LocalSerialTransport(e,config());u.discover();u.openTransport();e.receiveFails=true;
        rejects(()->u.receive(new byte[1],1));check(u.state()==LocalSerialTransport.State.FAILED,"receive exception fails transport");u.close();
    }
    private static void negativeDiscoveryStatus() {
        FakeDriver d=new FakeDriver();d.connectType=2;LocalSerialTransport t=new LocalSerialTransport(d,config());
        try {
            d.duringDiscover=()->d.callbacks.connection(d.id,false,0,"private NAT2 discovery branch failure");
            check(t.discover()==20001 && t.state()==LocalSerialTransport.State.DISCOVERED,"negative NAT2 discovery status preserves supported result");
            check(t.lastNativeError()==77,"discovery native error retained privately");
            LocalSerialTransport.Event event=t.pollEvent();
            check(event.kind()==LocalSerialTransport.Event.Kind.CONNECTION && !event.connected(),"negative discovery status retained privately");
            check(t.openTransport()==0 && t.state()==LocalSerialTransport.State.OPEN,"NAT1 polling path opens after NAT2 discovery failure");
            check(t.receive(new byte[1],1)==0,"poll receive remains available");
        } finally { t.close(); }
    }
    private static void negativeOpeningStatus(int connectType) {
        FakeDriver d=new FakeDriver();d.connectType=connectType;LocalSerialTransport t=new LocalSerialTransport(d,config());
        try {
            t.discover();d.duringOpen=()->{
                d.callbacks.connection(d.id,false,20001,"private NAT2 opening branch failure");
                check(t.state()==LocalSerialTransport.State.OPENING,"opening NAT2 failure deferred until mode selected");
            };
            check(t.openTransport()==0,"SetValue result preserved independently of status");
            if(connectType==3) {
                check(t.receiveMode()==LocalSerialTransport.ReceiveMode.CALLBACK && t.state()==LocalSerialTransport.State.FAILED,"selected callback transport applies pending failure");
                check(d.callbacks.data(d.id,new byte[]{1})==0,"failed callback path drops bytes");
                rejects(()->t.send(new byte[1],1));
            } else {
                check(t.receiveMode()==LocalSerialTransport.ReceiveMode.POLL && t.state()==LocalSerialTransport.State.OPEN,"polling open survives pending NAT2 failure");
                check(t.receive(new byte[1],1)==0,"polling receive available after opening failure metadata");
            }
            check(!t.pollEvent().connected(),"opening negative status remains bounded private event");
        } finally { t.close(); }
    }
    private static void negativeEstablishedStatus(int connectType) {
        FakeDriver d=new FakeDriver();d.connectType=connectType;LocalSerialTransport t=new LocalSerialTransport(d,config());
        try {
            t.discover();t.openTransport();d.callbacks.connection(d.id,false,20001,"private NAT2 established failure");
            if(connectType==3) {
                check(t.state()==LocalSerialTransport.State.FAILED,"established selected callback failure is terminal");
                check(d.callbacks.data(d.id,new byte[]{1})==0,"terminal callback failure drops bytes");
                rejects(()->t.send(new byte[1],1));
                d.callbacks.connection(d.id,true,20001,"late reconnect must not revive generation");
                check(t.state()==LocalSerialTransport.State.FAILED,"late positive callback cannot revive failed transport");
            } else {
                check(t.state()==LocalSerialTransport.State.OPEN,"independent polling transport survives NAT2 callback failure");
                d.recvResult=1;check(t.receive(new byte[1],1)==1,"polling bytes remain available after NAT2 status");
                check(t.send(new byte[1],1)==1,"polling send remains available after NAT2 status");
            }
            check(!t.pollEvent().connected(),"established negative metadata retained privately");
        } finally { t.close(); }
    }
    private static void workerAssertionPropagation() {
        AssertionError marker=new AssertionError("synthetic worker failure");
        Worker worker=new Worker(()->{throw marker;});
        boolean transferred=false;
        try { join(worker); } catch(AssertionError actual) { check(actual==marker,"exact worker assertion transferred");transferred=true; }
        check(transferred,"worker failure reaches main test thread");
    }
    private static String descriptor(Class<?> t) {
        if(t.isArray())return t.getName().replace('.','/');if(t==void.class)return "V";if(t==boolean.class)return "Z";if(t==int.class)return "I";if(t==long.class)return "J";return "L"+t.getName().replace('.','/')+";";
    }
    private static void descriptors() throws Exception {
        // Literal independently fixed original APK Java descriptors.
        String[] fixture={"Destroy(J)I","InitGlobal()I","Initialize()J","GetConnInfo(J)Ljava/lang/String;","GetConnectType(J)I","GetErrorCode(J)I","GetLastRecvTime(J)J","GetTraversalMode(J)I",
            "GetVersionType(JLjava/lang/String;Ljava/lang/String;ILjava/lang/String;I[BIIZLjava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)I",
            "Interrupt(J)I","Nat2EnablePrintLog(Z)I",
            "QueryDevInfo(JLjava/lang/String;Ljava/lang/String;ILjava/lang/String;ILjava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;",
            "RecvData(J[BI)I","SendData(J[BI)I","SetConnectTraversalMode(JI)I","SetDisableConnFlag(I)Z","SetLanIps(Ljava/lang/String;)Z","SetValue(JLjava/lang/String;Ljava/lang/String;II)I"};
        Set<String> actual=new HashSet<>();for(Method m:NatTraveral.class.getDeclaredMethods())if(Modifier.isNative(m.getModifiers())){StringBuilder s=new StringBuilder(m.getName()).append('(');for(Class<?> p:m.getParameterTypes())s.append(descriptor(p));actual.add(s.append(')').append(descriptor(m.getReturnType())).toString());}
        check(actual.size()==fixture.length,"native descriptor count");for(String s:fixture)check(actual.contains(s),"JNI "+s);
        check(NatTraveral.class.getMethod("Nat2ConnStatusCallback",long.class,boolean.class,int.class,String.class).getReturnType()==void.class,"status descriptor");
        check(NatTraveral.class.getMethod("Nat2RecvDataCallback",long.class,byte[].class).getReturnType()==int.class,"data descriptor");
        NatTraveral.LogPrintCallback("discard fixture log");rejects(NatTraveral::getInstance);
    }
    public static void main(String[] args) throws Exception {
        if(args.length>0 && args[0].equals("quarantine"))quarantine();
        else if(args.length>0 && args[0].equals("binding"))bindingClose();
        else if(args.length>0 && args[0].equals("removal"))removalFailure();
        else if(args.length>0 && args[0].equals("allocation"))allocationUncertainty();
        else if(args.length>0 && args[0].equals("fix-discovery"))negativeDiscoveryStatus();
        else if(args.length>0 && args[0].equals("fix-opening-poll"))negativeOpeningStatus(2);
        else if(args.length>0 && args[0].equals("fix-opening-callback"))negativeOpeningStatus(3);
        else if(args.length>0 && args[0].equals("fix-poll"))negativeEstablishedStatus(2);
        else if(args.length>0 && args[0].equals("fix-callback"))negativeEstablishedStatus(3);
        else if(args.length>0 && args[0].equals("fix-worker"))workerAssertionPropagation();
        else {descriptors();bounds();ordinary();polling();queue();failures();reentryAndRace();bindingClose();deadline();openingData();ioFailure();negativeDiscoveryStatus();negativeOpeningStatus(2);negativeOpeningStatus(3);negativeEstablishedStatus(2);negativeEstablishedStatus(3);workerAssertionPropagation();reusedEcho();}
        System.out.println("PASS local serial "+checks+" checks; synthetic host only");
    }
    private static final class FakeDriver implements LocalSerialDriver {
        long id=IDS.incrementAndGet();int type=20001,connectType=3,openResult,sendResult=1,recvResult,destroyCalls,interruptCalls;
        boolean destroyProved=true,registered,removalFails,allocationFails,sendFails,receiveFails;int allocateCalls;String serial,order="";Callbacks callbacks;Runnable duringDiscover,duringBind,duringOpen;
        public long allocate(){allocateCalls++;if(allocationFails)throw new IllegalStateException("synthetic allocation uncertainty");return id;}public void bind(long echo,Callbacks c){check(echo==id,"owned bind");callbacks=c;if(duringBind!=null)duringBind.run();registered=true;}
        public void removeCallbacks(long echo){order+="remove,";if(removalFails)throw new IllegalStateException("synthetic removal uncertainty");registered=false;}
        public int discover(long echo,LocalSerialConfig c){serial=c.serial();if(duringDiscover!=null)duringDiscover.run();return type;}
        public int openTransport(long echo,LocalSerialConfig c){if(duringOpen!=null)duringOpen.run();return openResult;}
        public int connectType(long echo){return connectType;}public int error(long echo){return 77;}
        public int send(long echo,byte[] b,int n){if(sendFails)throw new IllegalStateException("synthetic send failure");return sendResult;}
        public int receive(long echo,byte[] b,int n){if(receiveFails)throw new IllegalStateException("synthetic receive failure");if(recvResult>0 && recvResult<=n)Arrays.fill(b,0,recvResult,(byte)7);return recvResult;}
        public boolean interrupt(long echo){interruptCalls++;order+="interrupt,";return true;}
        public boolean destroy(long echo){destroyCalls++;order+="destroy";return destroyProved;}
    }
}
