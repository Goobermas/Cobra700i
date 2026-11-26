import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import java.io.*;

public class Boot extends GhidraScript {
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        Address a = toAddr("0xFFFA8708");
        Function f = getFunctionAt(a);
        if (f == null) f = createFunction(a, "reset_handler");
        println("RESET=" + (f==null?"NULL":f.getName()+" size="+f.getBody().getNumAddresses()));
        if (f == null) return;
        PrintWriter asm = new PrintWriter("out/ghidra/reset.asm");
        for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true))
            asm.println(i.getAddress()+"  "+i.toString());
        asm.close();
        PrintWriter cs = new PrintWriter("out/ghidra/reset_calls.csv");
        cs.println("from,to,name");
        for (Function g : f.getCalledFunctions(monitor))
            cs.println(a+","+g.getEntryPoint()+","+g.getName());
        cs.close();
        DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
        DecompileResults r = di.decompileFunction(f, 120, monitor);
        String c = r.getDecompiledFunction()==null?"(none)":r.getDecompiledFunction().getC();
        PrintWriter pw = new PrintWriter("out/ghidra/reset.c"); pw.println(c); pw.close();
        println("OK="+r.decompileCompleted()+" ERR="+r.getErrorMessage());
        for (int k=0;k<12;k++) {
            Address va = toAddr(0xFFFFFFD0L + 4L*k);
            long v = mem.getInt(va) & 0xFFFFFFFFL;
            println("VEC "+va+" -> 0x"+Long.toHexString(v));
        }
        int good=0, bad=0;
        for (int k=0;k<256;k++) {
            Address va = toAddr(0xFFF57750L + 4L*k);
            long v = mem.getInt(va) & 0xFFFFFFFFL;
            if (k<6) println("RELVEC "+k+" -> 0x"+Long.toHexString(v));
            if (v>=0xFFF00000L) good++; else bad++;
        }
        println("RELVEC good="+good+" bad="+bad);
        println("===PSEUDO==="); println(c);
    }
}
