import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import java.io.*;

public class Inventory extends GhidraScript {
    public void run() throws Exception {
        Address a = toAddr("0xFFFA8708");
        Function f = getFunctionAt(a);
        println("RESET=" + (f==null?"NULL":f.getName()+" body="+f.getBody().getNumAddresses()));
        if (f != null) {
            DecompInterface di = new DecompInterface();
            di.openProgram(currentProgram);
            DecompileResults r = di.decompileFunction(f, 120, monitor);
            println("OK=" + r.decompileCompleted() + " ERR=" + r.getErrorMessage());
            println("===RESET_PSEUDO===");
            println(r.getDecompiledFunction()==null?"(none)":r.getDecompiledFunction().getC());
        }
        FunctionManager fm = currentProgram.getFunctionManager();
        int n=0;
        PrintWriter pw = new PrintWriter(new FileWriter("out/ghidra/functions.csv"));
        pw.println("addr,name,size,callers,callees");
        for (Function g : fm.getFunctions(true)) {
            n++;
            pw.println(g.getEntryPoint()+","+g.getName()+","+g.getBody().getNumAddresses()+","
                       +g.getCallingFunctions(monitor).size()+","+g.getCalledFunctions(monitor).size());
        }
        pw.close();
        println("TOTAL_FUNCS="+n);
    }
}
