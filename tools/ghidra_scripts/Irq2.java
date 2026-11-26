import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class Irq2 extends GhidraScript {
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        Map<Long,List<Integer>> m = new TreeMap<>();
        for (int k=0;k<256;k++) {
            long v = mem.getInt(toAddr(0xFFF57750L+4L*k)) & 0xFFFFFFFFL;
            m.computeIfAbsent(v, z->new ArrayList<>()).add(k);
        }
        PrintWriter vec = new PrintWriter("out/ghidra/irq_vectors.csv");
        vec.println("target,vector_count,vector_indices,size,calls,decompiled");
        PrintWriter reg = new PrintWriter("out/ghidra/irq_registers.csv");
        reg.println("target,kind,address");
        for (Map.Entry<Long,List<Integer>> e : m.entrySet()) {
            long v = e.getKey();
            String h = String.format("%08X", v);
            Function f = getFunctionAt(toAddr(v));
            if (f == null) { vec.println("0x"+h+",0,?,0,0,NOFUNC"); continue; }
            StringBuilder cb = new StringBuilder();
            for (Function g : f.getCalledFunctions(monitor))
                cb.append(String.format("%08X", g.getEntryPoint().getOffset())).append(" ");
            vec.println("0x"+h+","+e.getValue().size()+",\""+e.getValue()+"\","
                       +f.getBody().getNumAddresses()+",\""+cb.toString().trim()+"\",yes");
            Set<Long> per = new TreeSet<>(), ram = new TreeSet<>();
            for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true))
                for (int o=0;o<i.getNumOperands();o++)
                    for (Object ob : i.getOpObjects(o))
                        if (ob instanceof Scalar) {
                            long s = ((Scalar)ob).getUnsignedValue();
                            if (s>=0x80000L && s<0x100000L) per.add(s);
                            else if (s>=0x1000L && s<0x80000L) ram.add(s);
                        }
            for (long s : per) reg.println("0x"+h+",PERIPH,0x"+String.format("%08X", s));
            for (long s : ram) reg.println("0x"+h+",RAM,0x"+String.format("%08X", s));
        }
        vec.close(); reg.close();
        println("WROTE vectors="+m.size());
    }
}
