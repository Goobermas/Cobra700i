import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class Decomp extends GhidraScript {
    public void run() throws Exception {
        Address a = toAddr("0xFFFB2BA1");
        Function f = getFunctionAt(a);
        if (f == null) { f = createFunction(a, "tone"); }
        println("FUNC=" + (f==null?"NULL":f.getName()+" "+f.getEntryPoint()+" body="+f.getBody().getNumAddresses()));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        DecompileResults r = di.decompileFunction(f, 120, monitor);
        println("DECOMP_OK=" + r.decompileCompleted() + " ERR=" + r.getErrorMessage());
        println("===PSEUDO===");
        if (r.getDecompiledFunction()!=null) println(r.getDecompiledFunction().getC()); else println("(none)");
        println("===ASM===");
        for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true)) println(i.getAddress()+"  "+i.toString());
        println("===CALLERS===");
        for (Function c : f.getCallingFunctions(monitor)) println(c.getName()+" @ "+c.getEntryPoint());
    }
}
