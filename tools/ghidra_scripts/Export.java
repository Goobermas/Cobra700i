import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class Export extends GhidraScript {
    public void run() throws Exception {
        int limit = Integer.parseInt(System.getenv().getOrDefault("PASS_LIMIT","120"));
        int offset = Integer.parseInt(System.getenv().getOrDefault("PASS_OFFSET","0"));
        DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
        int n=0, done=0, ok=0; long total=currentProgram.getFunctionManager().getFunctionCount();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            n++;
            if (n <= offset) continue;
            if (done >= limit) break;
            String h = f.getEntryPoint().toString();
            DecompileResults d = di.decompileFunction(f, 45, monitor);
            PrintWriter c = new PrintWriter("out/ghidra/funcs/"+h+".c");
            c.println("// "+h+" "+f.getName()+" size="+f.getBody().getNumAddresses());
            c.println("// callers="+f.getCallingFunctions(monitor).size()+" callees="+f.getCalledFunctions(monitor).size());
            c.println(d.getDecompiledFunction()==null?"// no decompilation":d.getDecompiledFunction().getC());
            c.close();
            PrintWriter a = new PrintWriter("out/ghidra/funcs/"+h+".asm");
            for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true))
                a.println(i.getAddress()+"  "+i.toString());
            a.close();
            if (d.decompileCompleted()) ok++;
            done++;
            // atomic checkpoint after each function's files are written
            FileOutputStream fo = new FileOutputStream("out/ghidra/passes/ctl.json.tmp");
            fo.write(("{\"next\": "+(offset+done)+", \"done\": "+done+", \"total\": "+total
                      +", \"decompiled_ok\": "+ok+", \"last\": \""+h+"\"}").getBytes());
            fo.close();
            new File("out/ghidra/passes/ctl.json.tmp").renameTo(new File("out/ghidra/passes/ctl.json"));
        }
        println("EXPORT offset="+offset+" done="+done+" ok="+ok+" total="+total);
    }
}
