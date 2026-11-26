import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

public class Export extends GhidraScript {
    public void run() throws Exception {
        int limit = Integer.parseInt(System.getenv().getOrDefault("PASS_LIMIT","120"));
        int offset = Integer.parseInt(System.getenv().getOrDefault("PASS_OFFSET","0"));
        if (limit <= 0 || offset < 0) throw new IllegalArgumentException("Invalid export window");
        String output = System.getenv().getOrDefault("KALAB_OUT_DIR", "out/ghidra");
        Path funcs = Paths.get(output, "funcs");
        Path passes = Paths.get(output, "passes");
        Files.createDirectories(funcs);
        Files.createDirectories(passes);
        DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
        int n=0, done=0, ok=0; long total=currentProgram.getFunctionManager().getFunctionCount();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            n++;
            if (n <= offset) continue;
            if (done >= limit) break;
            String h = f.getEntryPoint().toString();
            DecompileResults d = di.decompileFunction(f, 45, monitor);
            if (!d.decompileCompleted() || d.getDecompiledFunction()==null)
                throw new IOException("Decompiler failed at " + h + ": " + d.getErrorMessage());
            File cFinal = funcs.resolve(h+".c").toFile();
            File aFinal = funcs.resolve(h+".asm").toFile();
            File cTmp = new File(cFinal.getPath()+".tmp");
            File aTmp = new File(aFinal.getPath()+".tmp");
            PrintWriter c = new PrintWriter(cTmp, StandardCharsets.UTF_8.name());
            c.println("// "+h+" "+f.getName()+" size="+f.getBody().getNumAddresses());
            c.println("// callers="+f.getCallingFunctions(monitor).size()+" callees="+f.getCalledFunctions(monitor).size());
            c.println(d.getDecompiledFunction().getC());
            if (c.checkError()) throw new IOException("Failed C export: " + h);
            c.close();
            PrintWriter a = new PrintWriter(aTmp, StandardCharsets.UTF_8.name());
            for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true))
                a.println(i.getAddress()+"  "+i.toString());
            if (a.checkError()) throw new IOException("Failed assembly export: " + h);
            a.close();
            // Atomic replaces: a crash mid-print cannot truncate a completed export.
            Files.move(cTmp.toPath(), cFinal.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            Files.move(aTmp.toPath(), aFinal.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            ok++;
            done++;
            // atomic checkpoint after each function's files are written
            FileOutputStream fo = new FileOutputStream(passes.resolve("ctl.json.tmp").toFile());
            fo.write(("{\"next\": "+(offset+done)+", \"done\": "+done+", \"total\": "+total
                      +", \"decompiled_ok\": "+ok+", \"last\": \""+h+"\"}").getBytes());
            fo.close();
            Files.move(passes.resolve("ctl.json.tmp"), passes.resolve("ctl.json"),
                       StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        }
        println("EXPORT offset="+offset+" done="+done+" ok="+ok+" total="+total);
    }
}
