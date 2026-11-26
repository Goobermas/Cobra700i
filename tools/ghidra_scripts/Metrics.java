import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class Metrics extends GhidraScript {
    public void run() throws Exception {
        String lim = System.getenv("PASS_LIMIT");
        String off = System.getenv("PASS_OFFSET");
        int limit = lim==null?200:Integer.parseInt(lim);
        int offset = off==null?0:Integer.parseInt(off);
        DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
        PrintWriter pw = new PrintWriter("out/ghidra/passes/metrics_"+offset+".csv");
        pw.println("addr,name,size,insns,callers,callees,indirect,globals,bad,decompiled,score");
        int n=0, done=0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            n++;
            if (n <= offset) continue;
            if (done >= limit) { pw.println("NEXT_OFFSET,"+n); break; }
            done++;
            int ins=0, bad=0, ind=0;
            for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                ins++;
                String m = i.getMnemonicString();
                if (m == null || m.equalsIgnoreCase("BAD") || i.toString().contains("BAD")) bad++;
                for (Reference r : i.getReferencesFrom())
                    if (r.getReferenceType().isIndirect() || r.getReferenceType().isComputed()) ind++;
            }
            DecompileResults d = di.decompileFunction(f, 45, monitor);
            String c = d.getDecompiledFunction()==null?"":d.getDecompiledFunction().getC();
            int glob = count(c,"DAT_") + count(c,"_DAT_");
            int callers = f.getCallingFunctions(monitor).size();
            int callees = f.getCalledFunctions(monitor).size();
            int score = 100;
            if (!d.decompileCompleted()) score -= 40;
            if (bad>0) score -= Math.min(20, bad*2);
            if (ins==0) score -= 30;
            if (ind>0) score -= Math.min(10, ind);
            if (glob>0) score -= Math.min(10, glob/3);
            if (callers==0 && callees==0) score -= 10;
            if (score<0) score=0;
            pw.println(f.getEntryPoint()+","+f.getName()+","+f.getBody().getNumAddresses()+","
                      +ins+","+callers+","+callees+","+ind+","+glob+","+bad+","
                      +d.decompileCompleted()+","+score);
        }
        pw.close();
        println("PASS offset="+offset+" processed="+done+" total_functions="+n);
    }
    int count(String s, String t) { int c=0,i=0; while((i=s.indexOf(t,i))>=0){c++;i+=t.length();} return c; }
}
