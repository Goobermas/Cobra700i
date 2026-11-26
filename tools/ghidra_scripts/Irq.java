import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import java.io.*;
import java.util.*;

public class Irq extends GhidraScript {
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
        Map<Long,List<Integer>> m = new TreeMap<>();
        for (int k=0;k<256;k++) {
            long v = mem.getInt(toAddr(0xFFF57750L+4L*k)) & 0xFFFFFFFFL;
            m.computeIfAbsent(v, z->new ArrayList<>()).add(k);
        }
        PrintWriter idx = new PrintWriter("out/ghidra/irq/index.csv");
        idx.println("target,vectors,count,size,ok");
        for (Map.Entry<Long,List<Integer>> e : m.entrySet()) {
            long v = e.getKey();
            if (v < 0xFFF00000L) continue;
            Address a = toAddr(v);
            Function f = getFunctionAt(a);
            if (f == null) f = createFunction(a, null);
            if (f == null) { idx.println("0x"+Long.toHexString(v)+",?,0,0,NOFUNC"); continue; }
            DecompileResults r = di.decompileFunction(f, 90, monitor);
            String c = r.getDecompiledFunction()==null?"(none)":r.getDecompiledFunction().getC();
            String h = Long.toHexString(v);
            PrintWriter p = new PrintWriter("out/ghidra/irq/"+h+".c");
            p.println("// "+f.getName()+" @"+a+" size="+f.getBody().getNumAddresses()+" vectors="+e.getValue());
            p.println(c); p.close();
            PrintWriter q = new PrintWriter("out/ghidra/irq/"+h+".asm");
            for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true)) q.println(i.getAddress()+"  "+i.toString());
            q.close();
            StringBuilder cb = new StringBuilder();
            for (Function g : f.getCalledFunctions(monitor)) cb.append(Long.toHexString(g.getEntryPoint().getOffset())).append(" ");
            idx.println("0x"+h+","+e.getValue().size()+","+e.getValue().size()+","+f.getBody().getNumAddresses()+","+r.decompileCompleted());
            println("H "+h+" vec="+e.getValue().size()+" size="+f.getBody().getNumAddresses()+" calls=["+cb+"]");
        }
        idx.close();
        Function disp = getFunctionAt(toAddr(0xFFFA850AL));
        if (disp != null) {
            println("CALLERS_OF_FFFA850A=" + disp.getCallingFunctions(monitor).size());
            for (Function g : disp.getCallingFunctions(monitor)) println("  caller "+g.getName()+" @"+g.getEntryPoint());
        }
        PrintWriter fp = new PrintWriter("out/ghidra/functions.csv");
        fp.println("addr,name,size,callers,callees");
        int n=0;
        for (Function g : currentProgram.getFunctionManager().getFunctions(true)) {
            n++;
            fp.println(g.getEntryPoint()+","+g.getName()+","+g.getBody().getNumAddresses()+","
                       +g.getCallingFunctions(monitor).size()+","+g.getCalledFunctions(monitor).size());
        }
        fp.close();
        println("TOTAL_FUNCS="+n);
    }
}
