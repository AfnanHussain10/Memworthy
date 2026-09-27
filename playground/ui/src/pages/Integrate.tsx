// How to use the library: install, three snippets, and the CLI tools.
import { useEffect } from "react";
import { track } from "../api";

export function Integrate() {
  useEffect(() => track("integrate_page"), []);
  return (
    <div className="page">
      <h1>Integrate</h1>
      <p className="lead">Memworthy sits between your extractor and your memory store. It never writes on its own; it returns a decision you can act on, and logs every one.</p>
      <pre>{`pip install "memworthy[jev]"          # core + Jev judge
pip install "memworthy[jev,mem0]"     # plus the Mem0 wrapper
export TYPESAFE_API_KEY=...`}</pre>

      <h2>1. Gate candidate facts (any backend)</h2>
      <pre>{`from memworthy import Candidate, DictStore, Gate

gate = Gate(policy="personal-memory", store=DictStore())
for d in gate.evaluate([Candidate.from_text("I'm in Dubai this week")]):
    print(d.action, d.rule, d.type)       # reject not_memory temporary`}</pre>

      <h2>2. Wrap a Mem0 client</h2>
      <pre>{`from mem0 import Memory
from memworthy import GatedMemory

memory = GatedMemory(Memory(), policy="personal-memory")
memory.add([{"role": "user", "content": "I live in Lahore"}], user_id="alice")`}</pre>

      <h2>3. Turn coding sessions into a Markdown knowledge base</h2>
      <pre>{`memworthy run dev-sessions ~/.claude/projects --store markdown:~/kb`}</pre>

      <h2>Tools</h2>
      <dl className="tools">
        <dt><code>memworthy.ledger.jsonl</code></dt><dd>Every decision, append-only, in the format the playground downloads.</dd>
        <dt><code>memworthy replay</code></dt><dd>Shows which past decisions a policy change would flip, like the timeline after you edit a rule.</dd>
        <dt><code>memworthy test</code></dt><dd>Runs a policy's built-in examples in CI with recorded answers.</dd>
      </dl>
    </div>
  );
}
