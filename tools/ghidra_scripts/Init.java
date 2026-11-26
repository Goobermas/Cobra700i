import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import java.io.*;
import java.util.*;

public class Init extends GhidraScript {
    long[] A = {0xFFFAA2A4L,0xFFFC71B1L,0xFFFA8AA2L,0xFFFA8422L,0xFFFA8B07L,
                0xFFFA8A80L,0xFFFA8318L,0xFFFA8BDAL,0xFFF93A4CL,0xFFFA850AL};
    public void run() throws Exception {
        DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
        for (long x : A) {
            Address a = toAddr(x);
            Function f = getFunctionAt(a);
            if (f == null) f = createFunction(a, null);
            if (f == null) { println("FAIL "+Long.toHexString(x)); continue; }
            DecompileResults r = di.decompileFunction(f, 120, monitor);
            String c = r.getDecompiledFunction()==null?"(none)":r.getDecompiledFunction().getC();
            PrintWriter p = new PrintWriter("out/ghidra/init/"+Long.toHexString(x)+".c");
            p.println("// "+f.getName()+" @"+a+" size="+f.getBody().getNumAddresses()); p.println(c); p.close();
            StringBuilder sb = new StringBuilder();
            for (Function g : f.getCalledFunctions(monitor)) sb.append(g.getEntryPoint()).append(" ");
            println("FN "+Long.toHexString(x)+" size="+f.getBody().getNumAddresses()
                    +" ok="+r.decompileCompleted()+" calls=["+sb+"]");
        }
        Memory mem = currentProgram.getMemory();
        Map<Long,Integer> cnt = new TreeMap<>();
        for (int k=0;k<256;k++) {
            long v = mem.getInt(toAddr(0xFFF57750L+4L*k)) & 0xFFFFFFFFL;
            cnt.merge(v,1,Integer::sum);
        }
        println("UNIQUE_TARGETS="+cnt.size());
        int made=0;
        for (Map.Entry<Long,Integer> e : cnt.entrySet()) {
            if (e.getKey() < 0xFFF00000L) continue;
            if (getFunctionAt(toAddr(e.getKey()))==null && createFunction(toAddr(e.getKey()), null)!=null) made++;
        }
        println("FUNCS_CREATED_AT_VECTORS="+made);
        PrintWriter vp = new PrintWriter("out/ghidra/vector_targets.csv");
        vp.println("target,count");
        for (Map.Entry<Long,Integer> e : cnt.entrySet()) vp.println("0x"+Long.toHexString(e.getKey())+","+e.getValue());
        vp.close();
    }
}
