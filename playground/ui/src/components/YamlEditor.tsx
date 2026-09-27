// CodeMirror YAML editor with the invalid line highlighted. Loaded lazily (it is the heaviest chunk).
import { useMemo } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { yaml } from "@codemirror/lang-yaml";
import { Decoration, EditorView } from "@codemirror/view";
import { RangeSetBuilder } from "@codemirror/state";

interface Props {
  value: string;
  onChange: (v: string) => void;
  errorLine: number | null;
  dark: boolean;
}

export default function YamlEditor({ value, onChange, errorLine, dark }: Props) {
  const extensions = useMemo(() => {
    const exts = [yaml(), EditorView.lineWrapping];
    if (errorLine) {
      exts.push(EditorView.decorations.compute(["doc"], (state) => {
        const b = new RangeSetBuilder<Decoration>();
        if (errorLine <= state.doc.lines) {
          const line = state.doc.line(errorLine);
          b.add(line.from, line.from, Decoration.line({ class: "cm-error-line" }));
        }
        return b.finish();
      }));
    }
    return exts;
  }, [errorLine]);
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={extensions}
      theme={dark ? "dark" : "light"}
      height="100%"
      aria-label="Policy YAML"
      basicSetup={{ foldGutter: false, highlightActiveLine: true }}
    />
  );
}
