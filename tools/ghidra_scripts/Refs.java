import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class Refs extends GhidraScript {
    public void run() throws Exception {
        PrintWriter pw = new PrintWriter("out/ghidra/refs.csv");
        pw.println("from_func,from_instr,to,kind");
        int n=0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                for (Reference r : i.getReferencesFrom()) {
                    RefType t = r.getReferenceType();
                    String k;
                    if (t.isCall()) k = t.isIndirect() ? "call_indirect" : "call";
                    else if (t.isJump()) k = t.isIndirect() ? "jump_indirect" : "jump";
                    else if (t.isData()) k = "data";
                    else k = "other";
                    pw.println(f.getEntryPoint()+","+i.getAddress()+","+r.getToAddress()+","+k);
                    n++;
                }
            }
        }
        pw.close();
        println("REFS="+n);
    }
}
