import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Citation, type QaAttachment } from "../api";

interface Msg {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  confidence?: number;
  refused?: boolean;
  mode?: "grounded" | "general";
  attachments?: QaAttachment[];
}

const TOPIC_SECTIONS = [
  {
    title: "Engineering fundamentals",
    topics: ["Statics, dynamics & kinematics", "Mechanics of materials", "Vibrations, acoustics & engineering math"],
  },
  {
    title: "Design, materials & failure",
    topics: ["Machine elements & mechanisms", "Material selection & metallurgy", "Fatigue, fracture, wear & corrosion"],
  },
  {
    title: "CAD, CAM & simulation",
    topics: [
      "SolidWorks & Fusion 360 3D modeling",
      "CAD assemblies, drawings & GD&T",
      "CNC CAM toolpaths, setups & G-code",
      "Milling, turning, tooling & workholding",
      "ANSYS, Abaqus & FEA simulation",
      "CAD/CAM macros, scripts & automation",
    ],
  },
  {
    title: "Automotive & mobility",
    topics: ["Engines, EVs & powertrains", "Vehicle dynamics & braking", "Autonomous systems & robotics"],
  },
  {
    title: "Manufacturing",
    topics: ["Machining & process planning", "Welding, casting & forming", "Metrology & quality"],
  },
  {
    title: "Thermal & fluids",
    topics: ["Thermodynamics & power cycles", "Heat transfer, HVAC & refrigeration", "Fluid mechanics, CFD & turbomachinery"],
  },
  {
    title: "Mechatronics & control",
    topics: ["Control systems & instrumentation", "Robotics, sensors & actuators", "Automation, PLCs & embedded systems"],
  },
  {
    title: "Reliability & testing",
    topics: ["Fatigue & vibration", "Inspection & troubleshooting", "Maintenance & reliability"],
  },
];

const SUGGESTIONS = [
  "Estimate brake rotor temperature under repeated stops",
  "Design a parametric mounting bracket in SolidWorks",
  "Plan a CNC milling toolpath for an aluminum bracket",
  "Set up a mesh-convergence study for a bracket in ANSYS",
];

type SceneTopic = "mechanical" | "cad" | "automotive" | "thermal" | "manufacturing" | "robotics" | "reliability";

const SCENE_META: Record<SceneTopic, { label: string; mark: string }> = {
  mechanical: { label: "Machine design", mark: "⚙" },
  cad: { label: "CAD / CAE studio", mark: "⬡" },
  automotive: { label: "Mobility systems", mark: "◉" },
  thermal: { label: "Thermal flow", mark: "≈" },
  manufacturing: { label: "Manufacturing", mark: "▧" },
  robotics: { label: "Autonomous systems", mark: "⌘" },
  reliability: { label: "Reliability lab", mark: "∿" },
};

function sceneForQuestion(question: string): SceneTopic {
  const text = question.toLowerCase();
  if (/\b(solidworks|solid works|fusion\s*360|ansys|abaqus|finite element|\bfea\b|\bcad\b|\bcae\b|\bcam\b|cnc|toolpath|g[- ]?code|mastercam|feeds? and speeds?|mesh convergence|parametric model|3d model)\b/.test(text)) return "cad";
  if (/\b(robot\w*|autonom\w*|sensor\w*|actuat\w*|path planning)\b/.test(text)) return "robotics";
  if (/\b(vehicle\w*|automotive|car|engine\w*|powertrain|brak\w*|ev|electric vehicle|drivetrain|suspension)\b/.test(text)) return "automotive";
  if (/\b(therm\w*|heat|temperature|hvac|fluid\w*|flow|turbine|combustion|cool\w*)\b/.test(text)) return "thermal";
  if (/\b(manufactur\w*|machin\w*|weld\w*|cast\w*|form\w*|cnc|process plan|additive|3d print|metrology)\b/.test(text)) return "manufacturing";
  if (/\b(reliab\w*|fatigue|vibrat\w*|failure|inspect\w*|mainten\w*|test\w*|bearing life)\b/.test(text)) return "reliability";
  return "mechanical";
}

function restoreMessages(messages: Awaited<ReturnType<typeof api.qaThreads>>["items"][number]["messages"]): Msg[] {
  return messages.map((message) => ({
    role: message.role,
    content: message.content,
    citations: message.citations,
    confidence: message.confidence,
    attachments: message.attachments ?? [],
    mode: message.citations.length > 0 ? "grounded" : "general",
  }));
}

function readMathGroup(source: string, start: number): [string, number] {
  let index = start;
  while (/\s/.test(source[index] ?? "")) index += 1;
  if (source[index] !== "{") {
    if (source[index] === "\\") {
      const command = source.slice(index).match(/^\\[a-zA-Z]+|^\\./)?.[0] ?? "\\";
      return [command, index + command.length];
    }
    return [source[index] ?? "", Math.min(index + 1, source.length)];
  }
  const contentStart = index + 1;
  let depth = 1;
  index = contentStart;
  while (index < source.length && depth > 0) {
    if (source[index] === "\\") { index += 2; continue; }
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    index += 1;
  }
  return [source.slice(contentStart, depth === 0 ? index - 1 : index), index];
}

const MATH_SYMBOLS: Record<string, string> = {
  cdot: "·", times: "×", div: "÷", pm: "±", mp: "∓", le: "≤", leq: "≤", ge: "≥", geq: "≥",
  neq: "≠", approx: "≈", infty: "∞", pi: "π", theta: "θ", Delta: "Δ", delta: "δ", lambda: "λ",
  mu: "μ", rho: "ρ", omega: "ω", beta: "β", alpha: "α", tau: "τ", phi: "φ", sigma: "σ",
  epsilon: "ε", varepsilon: "ϵ", gamma: "γ", eta: "η", kappa: "κ", nu: "ν", xi: "ξ", psi: "ψ", partial: "∂",
  nabla: "∇", degree: "°", cdots: "⋯", sum: "∑", int: "∫", prime: "′",
};

function parseMath(source: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let index = 0;

  const atom = (): ReactNode => {
    const char = source[index];
    if (char === "{") {
      const [group, next] = readMathGroup(source, index);
      index = next;
      return <span className="math-group">{parseMath(group)}</span>;
    }
    if (char === "\\") {
      const command = source.slice(index).match(/^\\([a-zA-Z]+)|^\\(.)/);
      if (!command) { index += 1; return null; }
      const name = command[1] ?? command[2] ?? "";
      index += command[0].length;
      if (["frac", "dfrac", "tfrac", "binom"].includes(name)) {
        const [numerator, afterNumerator] = readMathGroup(source, index);
        const [denominator, afterDenominator] = readMathGroup(source, afterNumerator);
        index = afterDenominator;
        return <span className={`math-fraction ${name === "binom" ? "math-binomial" : ""}`}><span>{parseMath(numerator)}</span><span>{parseMath(denominator)}</span></span>;
      }
      if (name === "sqrt") {
        const [radicand, next] = readMathGroup(source, index);
        index = next;
        return <span className="math-root"><span aria-hidden="true">√</span><span>{parseMath(radicand)}</span></span>;
      }
      if (["text", "mathrm", "operatorname", "mathbf"].includes(name)) {
        const [text, next] = readMathGroup(source, index);
        index = next;
        return <span className={name === "mathbf" ? "math-bold" : "math-text"}>{text.replace(/\\([a-zA-Z]+)/g, "$1")}</span>;
      }
      if (["left", "right", "displaystyle", "textstyle", "quad", "qquad"].includes(name)) return null;
      if (name === "dot") {
        const target = atom();
        return <span className="math-dot">{target}<sup>·</sup></span>;
      }
      return <span>{MATH_SYMBOLS[name] ?? name}</span>;
    }
    index += 1;
    if (char === undefined) return null;
    if (/\d/.test(char)) return <span className="math-number">{char}</span>;
    if (/[a-zA-Z]/.test(char)) return <span className="math-variable">{char}</span>;
    if (/\s/.test(char)) return " ";
    return <span className="math-operator">{char}</span>;
  };

  while (index < source.length) {
    if (source[index] === "}") { index += 1; continue; }
    const base = atom();
    if (base === null) continue;
    let subscript: ReactNode | null = null;
    let superscript: ReactNode | null = null;
    while (index < source.length && /\s/.test(source[index] ?? "")) index += 1;
    while (source[index] === "_" || source[index] === "^") {
      const script = source[index];
      index += 1;
      const [argument, next] = readMathGroup(source, index);
      index = next;
      if (script === "_") subscript = <sub>{parseMath(argument)}</sub>;
      else superscript = <sup>{parseMath(argument)}</sup>;
      while (index < source.length && /\s/.test(source[index] ?? "")) index += 1;
    }
    nodes.push(subscript || superscript
      ? <span className="math-scripted">{base}{subscript}{superscript}</span>
      : base);
  }
  return nodes;
}

function MathExpression({ expression, display = false }: { expression: string; display?: boolean }) {
  return <span className={display ? "math-expression math-display" : "math-expression"} role="math" aria-label={expression.trim()}>
    {parseMath(expression.replace(/\\(left|right|displaystyle|textstyle)\b/g, ""))}
  </span>;
}

function renderInline(text: string) {
  const tokens = text.split(/(\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$\$[\s\S]+?\$\$|\$[^$\n]+\$|\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return tokens.map((part, index) => {
    if (part.startsWith("\\[") && part.endsWith("\\]")) return <MathExpression key={index} expression={part.slice(2, -2)} display />;
    if (part.startsWith("\\(") && part.endsWith("\\)")) return <MathExpression key={index} expression={part.slice(2, -2)} />;
    if (part.startsWith("$$") && part.endsWith("$$")) return <MathExpression key={index} expression={part.slice(2, -2)} display />;
    if (part.startsWith("$") && part.endsWith("$")) return <MathExpression key={index} expression={part.slice(1, -1)} />;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    return <span key={index}>{part}</span>;
  });
}

function FormattedAnswer({ content }: { content: string }) {
  const normalized = content.trim().replace(/\\\[\s*([\s\S]*?)\s*\\\]/g, (_match, expression: string) => `\n$$\n${expression.trim()}\n$$\n`);
  const blocks = normalized.split(/\n\s*\n/).filter(Boolean);
  let nextOrderedNumber = 1;
  return <div className="formatted-answer">{blocks.map((block, index) => {
    const lines = block.split(/\r?\n/);
    const displayMath = block.match(/^\s*\$\$([\s\S]*?)\$\$\s*$/);
    if (displayMath) {
      nextOrderedNumber = 1;
      return <MathExpression key={index} expression={displayMath[1] ?? ""} display />;
    }
    if (lines[0]?.startsWith("```") && lines[lines.length - 1]?.startsWith("```")) {
      nextOrderedNumber = 1;
      return <pre key={index}><code>{lines.slice(1, -1).join("\n")}</code></pre>;
    }
    if (lines.length === 1 && /^#{1,4}\s+/.test(lines[0] ?? "")) {
      nextOrderedNumber = 1;
      return <h3 key={index}>{renderInline((lines[0] ?? "").replace(/^#{1,4}\s+/, ""))}</h3>;
    }
    if (lines.every((line) => /^\s*[-*+]\s+/.test(line))) {
      nextOrderedNumber = 1;
      return <ul key={index}>{lines.map((line, itemIndex) => <li key={itemIndex}>{renderInline(line.replace(/^\s*[-*+]\s+/, ""))}</li>)}</ul>;
    }
    if (lines.every((line) => /^\s*\d+[.)]\s+/.test(line))) {
      const listedNumber = Number(lines[0]?.match(/^\s*(\d+)/)?.[1] ?? 1);
      const start = listedNumber === 1 && nextOrderedNumber > 1 ? nextOrderedNumber : listedNumber;
      nextOrderedNumber = start + lines.length;
      return <ol key={index} start={start}>{lines.map((line, itemIndex) => <li key={itemIndex}>{renderInline(line.replace(/^\s*\d+[.)]\s+/, ""))}</li>)}</ol>;
    }
    nextOrderedNumber = 1;
    return <p key={index}>{lines.map((line, lineIndex) => <span key={lineIndex}>{lineIndex > 0 && <br />}{renderInline(line)}</span>)}</p>;
  })}</div>;
}

export function AskPage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [savedThreads, setSavedThreads] = useState<{ id: string; title: string }[]>([]);
  const [deletingThreadId, setDeletingThreadId] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [sceneTopic, setSceneTopic] = useState<SceneTopic>("mechanical");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    api.qaThreads().then(({ items }) => {
      if (!active) return;
      setSavedThreads(items.map(({ id, title }) => ({ id, title })));
      const latest = items[0];
      if (latest) {
        setThreadId(latest.id);
        setMessages(restoreMessages(latest.messages));
        setSceneTopic(sceneForQuestion([...latest.messages].reverse().find((message) => message.role === "user")?.content ?? ""));
      }
    }).catch(() => {
      // Keep the conversation usable if loading past chats fails.
    }).finally(() => {
      if (active) setHistoryLoading(false);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const startNewChat = () => {
    setThreadId(null);
    setMessages([]);
    setInput("");
    setSceneTopic("mechanical");
    inputRef.current?.focus();
  };

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        startNewChat();
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);

  const openChat = async (id: string) => {
    if (id === threadId) return;
    try {
      const { items } = await api.qaThreads();
      const selected = items.find((item) => item.id === id);
      if (!selected) return;
      setThreadId(selected.id);
      setMessages(restoreMessages(selected.messages));
      setSceneTopic(sceneForQuestion([...selected.messages].reverse().find((message) => message.role === "user")?.content ?? ""));
      setInput("");
    } catch {
      // The active conversation remains open when history cannot be refreshed.
    }
  };

  const deleteChat = async (id: string) => {
    const selected = savedThreads.find((thread) => thread.id === id);
    if (!selected || busy || deletingThreadId) return;
    if (!window.confirm(`Delete “${selected.title}”? Its messages and generated images will be permanently removed.`)) return;

    setDeletingThreadId(id);
    try {
      await api.deleteQaThread(id);
      setSavedThreads((threads) => threads.filter((thread) => thread.id !== id));
      if (threadId === id) startNewChat();
    } catch (error) {
      window.alert(error instanceof Error ? `Couldn't delete this chat: ${error.message}` : "Couldn't delete this chat. Please try again.");
    } finally {
      setDeletingThreadId(null);
    }
  };

  const sendQuestion = async (question: string) => {
    if (!question || busy) return;
    setSceneTopic(sceneForQuestion(question));
    setInput("");
    setMessages((current) => [...current, { role: "user", content: question }]);
    setBusy(true);
    try {
      const wantsVideo = /\b(video|clip|animation)\b/i.test(question)
        && /\b(generate|make|create|produce|animate|show)\b/i.test(question);
      if (wantsVideo) {
        setMessages((current) => [...current, {
          role: "assistant",
          content: "Video generation is not connected in this deployment yet. I can generate engineering images, or write a frame-by-frame storyboard and motion brief for your video request.",
        }]);
        return;
      }
      const wantsImage = /\b(generate|make|create|draw|render|illustrate)\b.{0,60}\b(image|picture|illustration|diagram|schematic|rendering)\b/i.test(question)
        || /\b(image|picture|illustration|diagram|schematic|rendering)\b.{0,50}\b(of|showing|for)\b/i.test(question);
      if (wantsImage) {
        const result = await api.qaGenerateImage(question, threadId);
        setThreadId(result.thread_id);
        setSavedThreads((threads) => threads.some((thread) => thread.id === result.thread_id)
          ? threads
          : [{ id: result.thread_id, title: question.slice(0, 72) }, ...threads]);
        setMessages((current) => [...current, {
          role: "assistant",
          content: result.answer,
          attachments: [result.attachment],
        }]);
        return;
      }
      const answer = await api.qaAsk(question, threadId);
      setThreadId(answer.thread_id);
      setSavedThreads((threads) => threads.some((thread) => thread.id === answer.thread_id)
        ? threads
        : [{ id: answer.thread_id, title: question.slice(0, 72) }, ...threads]);
      setMessages((current) => [...current, {
        role: "assistant",
        content: answer.answer,
        citations: answer.citations,
        confidence: answer.confidence,
        refused: answer.refused,
        mode: answer.mode,
      }]);
    } catch (error) {
      setMessages((current) => [...current, {
        role: "assistant",
        content: `I couldn't complete that request. ${error instanceof Error ? error.message : "Please try again."}`,
      }]);
    } finally {
      setBusy(false);
    }
  };

  const ask = async (e: React.FormEvent) => {
    e.preventDefault();
    await sendQuestion(input.trim());
  };

  const useTopic = (topic: string) => {
    const question = `Give me a topic overview of ${topic}, including its subtopics, basic definitions, common formulas, assumptions, SI units, and verified values for any physical constants used.`;
    setSceneTopic(sceneForQuestion(topic));
    void sendQuestion(question);
  };

  return (
    <div className="copilot-layout">
      <aside className="copilot-sidebar" aria-label="Topics and chat history">
        <button type="button" className="new-chat-button" onClick={startNewChat}>
          <span>＋</span> New chat
          <kbd>Ctrl K</kbd>
        </button>

        <div className="sidebar-section-title">Explore topics</div>
        <div className="topic-list">
          {TOPIC_SECTIONS.map((section) => (
            <details className="topic-group" key={section.title} open={section.title === "Mechanical engineering"}>
              <summary>{section.title}</summary>
              <div className="topic-choices">
                {section.topics.map((topic) => (
                  <button type="button" key={topic} disabled={busy} onClick={() => useTopic(topic)}>{topic}</button>
                ))}
              </div>
            </details>
          ))}
        </div>

        <div className="sidebar-section-title history-title">Recent chats</div>
        <div className="chat-history-list">
          {historyLoading && <div className="sidebar-muted">Loading chats…</div>}
          {!historyLoading && savedThreads.length === 0 && <div className="sidebar-muted">Your conversations will appear here.</div>}
          {savedThreads.map((thread) => (
            <div className={`history-row ${thread.id === threadId ? "selected" : ""}`} key={thread.id}>
              <button
                type="button"
                className="history-item"
                onClick={() => openChat(thread.id)}
                title={thread.title}
              >
                <span>◷</span><span>{thread.title}</span>
              </button>
              <button
                type="button"
                className="delete-chat-button"
                aria-label={`Delete chat: ${thread.title}`}
                title="Delete chat"
                disabled={busy || deletingThreadId !== null}
                onClick={() => void deleteChat(thread.id)}
              >
                {deletingThreadId === thread.id ? <span className="spinner" /> : <svg aria-hidden="true" viewBox="0 0 16 16"><path d="M3 4.5h10M6 4.5V3h4v1.5m-5.5 0 .6 8h5.8l.6-8M6.5 7v3.5M9.5 7v3.5" /></svg>}
              </button>
            </div>
          ))}
        </div>
        <div className="copilot-sidebar-foot">Answers draw on broad model knowledge and your private saved conversations.</div>
      </aside>

      <section className="copilot-chat" data-scene={sceneTopic}>
        <div className="engineering-scene" aria-hidden="true">
          <div className="scene-label"><span /> {SCENE_META[sceneTopic].label}<small>LIVE CONCEPT VIEW</small></div>
          <div className="scene-stage">
            <div className="scene-grid-plane" />
            <div className="scene-orbit scene-orbit-one" />
            <div className="scene-orbit scene-orbit-two" />
            <div className="scene-cube">
              <i className="scene-face scene-front" />
              <i className="scene-face scene-back" />
              <i className="scene-face scene-right" />
              <i className="scene-face scene-left" />
              <i className="scene-face scene-top" />
              <i className="scene-face scene-bottom" />
              <span className="scene-mark">{SCENE_META[sceneTopic].mark}</span>
            </div>
            <span className="scene-axis scene-axis-x">X</span>
            <span className="scene-axis scene-axis-y">Y</span>
            <span className="scene-axis scene-axis-z">Z</span>
          </div>
        </div>
        <div className="chat-view-header">
          <span>{threadId ? savedThreads.find((thread) => thread.id === threadId)?.title || "Engineering chat" : "New chat"}</span>
          <span className="model-pill"><i /> Mechanical Copilot</span>
        </div>

        <div className={`chat-messages ${messages.length === 0 ? "empty-chat" : ""}`}>
          {messages.length === 0 && (
            <div className="chat-welcome">
              <div className="welcome-eyebrow"><span /> ENGINEERING DESK / 01</div>
              <div className="welcome-symbol">⚙</div>
              <h1>What can I help you solve?</h1>
              <p>Ask about mechanical design, vehicles, autonomous systems, manufacturing, thermal engineering, and more.</p>
              <div className="welcome-topics">
                {SUGGESTIONS.map((suggestion) => (
                  <button type="button" key={suggestion} onClick={() => { setInput(suggestion); setSceneTopic(sceneForQuestion(suggestion)); }}>{suggestion}<span>↗</span></button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message, index) => (
            <article key={`${index}-${message.role}`} className={`message-row ${message.role}`}>
              <div className={`message-avatar ${message.role}`}>{message.role === "assistant" ? "⚙" : "U"}</div>
              <div className={`message-content ${message.refused ? "refusal" : ""}`}>
                <div className="message-author">{message.role === "assistant" ? "Mechanical Copilot" : "You"}</div>
                <FormattedAnswer content={message.content} />
                {message.mode === "general" && <div className="answer-source-note">General engineering knowledge</div>}
                {message.attachments?.map((attachment) => (
                  <GeneratedMedia key={attachment.id} attachment={attachment} />
                ))}
                {message.citations && message.citations.length > 0 && (
                  <div className="message-citations">
                    <div className="citation-heading">Sources from your saved documents</div>
                    {message.citations.map((citation, citationIndex) => (
                      <span key={citationIndex} className="citation-chip" title={citation.snippet}>
                        {citation.source_ref || citation.title} · v{citation.version}
                      </span>
                    ))}
                    {typeof message.confidence === "number" && (
                      <span className="confidence-note">Confidence {(message.confidence * 100).toFixed(0)}%</span>
                    )}
                  </div>
                )}
              </div>
            </article>
          ))}
          {busy && <div className="assistant-thinking"><span className="spinner" /> Working through the engineering details…</div>}
          <div ref={endRef} />
        </div>

        <div className="composer-container">
          <form className="copilot-composer" onSubmit={ask}>
            <input
              ref={inputRef}
              value={input}
              onChange={(event) => { setInput(event.target.value); setSceneTopic(sceneForQuestion(event.target.value)); }}
              placeholder="Message Mechanical Copilot"
              aria-label="Message Mechanical Copilot"
            />
            <div className="composer-actions">
              <span className="composer-hint">Add details, dimensions, materials, and units for better results.</span>
              <button type="submit" disabled={busy || !input.trim()} aria-label="Send message">↑</button>
            </div>
          </form>
          <div className="composer-disclaimer">Engineering guidance can support your work; verify safety-critical decisions and plant-specific requirements.</div>
        </div>
      </section>
    </div>
  );
}

function GeneratedMedia({ attachment }: { attachment: QaAttachment }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    api.qaMediaObjectUrl(attachment.id).then((result) => {
      objectUrl = result;
      if (active) setUrl(result);
      else URL.revokeObjectURL(result);
    }).catch(() => setUrl(""));
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment.id]);

  if (!url) return <div className="generated-media-loading">Loading generated {attachment.kind}…</div>;
  return attachment.kind === "video"
    ? <video className="generated-media" controls preload="metadata" src={url} />
    : <a className="generated-media-link" href={url} download={`mechanical-copilot-${attachment.id}.png`}>
      <img className="generated-media" loading="lazy" src={url} alt={attachment.prompt || "Generated engineering illustration"} />
    </a>;
}
