"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { 
  ShieldAlert, Send, Zap, RefreshCw, ExternalLink, Cpu, Clock, HelpCircle, Activity
} from "lucide-react";

interface Battlecard {
  id: string;
  detected_change_type: string;
  executive_summary: string;
  previous_state: string;
  new_state: string;
  landmine_questions: string[];
  objection_rebuttal: string;
  verified_source_url: string;
  created_at: string;
  competitors: { name: string; domain: string } | null;
}

interface ChatMessage {
  role: "user" | "copilot";
  content: string;
  telemetry?: {
    model: string;
    intent: string;
    totalLatency: number;
    routingLatency: number;
  };
}

export default function AlphaDeskDashboard() {
  const [battlecards, setBattlecards] = useState<Battlecard[]>([]);
  const [loading, setLoading] = useState(true);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [inputQuery, setInputQuery] = useState("");
  const [isCopilotTyping, setIsCopilotTyping] = useState(false);

  const loadBattlecards = async () => {
    setLoading(true);
    const { data, error } = await supabase
      .from("battlecards")
      .select(`
        id, detected_change_type, executive_summary, previous_state,
        new_state, landmine_questions, objection_rebuttal, verified_source_url,
        created_at, competitors (name, domain)
      `)
      .order("created_at", { ascending: false });

    if (!error && data) {
      setBattlecards(data as any);
    }
    setLoading(false);
  };

  useEffect(() => {
    loadBattlecards();
  }, []);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputQuery.trim() || isCopilotTyping) return;

    const userText = inputQuery;
    setInputQuery("");
    setChatMessages((prev) => [...prev, { role: "user", content: userText }]);
    setIsCopilotTyping(true);

    try {
      const response = await fetch("http://localhost:8000/api/copilot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: userText }),
      });

      const resData = await response.json();

      setChatMessages((prev) => [
        ...prev,
        {
          role: "copilot",
          content: resData.answer,
          telemetry: {
            model: resData.model_used,
            intent: resData.intent,
            totalLatency: resData.total_latency,
            routingLatency: resData.routing_latency,
          },
        },
      ]);
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        {
          role: "copilot",
          content: "Failed to connect to the Copilot inference backend. Ensure api_server.py is running on port 8000.",
        },
      ]);
    } finally {
      setIsCopilotTyping(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur px-6 py-4 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
            <Zap className="h-5 w-5 fill-emerald-400/20" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
              AlphaDesk
              <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800/80 font-mono">
                Nemotron Tiered Architecture
              </span>
            </h1>
            <p className="text-xs text-slate-400">Autonomous Reconnaissance & Live Sales Copilot</p>
          </div>
        </div>
        <button onClick={loadBattlecards} className="flex items-center gap-2 text-xs font-semibold px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 transition-colors">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh Radar
        </button>
      </header>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-6 p-6 max-w-7xl mx-auto w-full">
        <section className="lg:col-span-7 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
              <Activity className="w-4 h-4 text-emerald-400" /> Live Competitor Battlecards
            </h2>
            <span className="text-xs text-slate-500 font-mono">{battlecards.length} Tracked Movements</span>
          </div>
          <div className="space-y-4 overflow-y-auto">
            {loading ? (
              <div className="p-8 text-center text-slate-500 font-mono text-sm border border-slate-800 rounded-xl bg-slate-900/40">
                Fetching intelligence signals from database...
              </div>
            ) : battlecards.length === 0 ? (
              <div className="p-8 text-center text-slate-500 font-mono text-sm border border-slate-800 rounded-xl bg-slate-900/40">
                No active battlecards found. Run Phase 3 to generate entries.
              </div>
            ) : (
              battlecards.map((card) => (
                <article key={card.id} className="rounded-xl border border-slate-800 bg-slate-900/70 p-5 shadow-sm space-y-4 hover:border-slate-700 transition">
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="text-xs font-mono text-emerald-400 uppercase tracking-wider">
                        {card.detected_change_type} DETECTED
                      </span>
                      <h3 className="text-base font-semibold text-white mt-0.5">
                        {card.competitors?.name || "Tracked Competitor"}
                      </h3>
                    </div>
                    {card.verified_source_url && (
                      <a href={card.verified_source_url} target="_blank" rel="noreferrer" className="text-xs text-slate-400 hover:text-emerald-400 flex items-center gap-1 font-mono transition">
                        Source <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                  <p className="text-sm text-slate-300 leading-relaxed">{card.executive_summary}</p>
                  <div className="bg-slate-950/60 rounded-lg p-3 border border-slate-800/80 text-xs">
                    <span className="font-semibold text-emerald-400 uppercase tracking-wider block mb-1">Recommended Rebuttal</span>
                    <p className="text-slate-300 italic">"{card.objection_rebuttal}"</p>
                  </div>
                  {card.landmine_questions && card.landmine_questions.length > 0 && (
                    <div className="space-y-1.5 text-xs">
                      <span className="font-semibold text-slate-400 flex items-center gap-1">
                        <HelpCircle className="w-3.5 h-3.5 text-amber-400" /> Trap Questions to Ask Prospects:
                      </span>
                      <ul className="list-disc pl-5 text-slate-400 space-y-1">
                        {card.landmine_questions.map((q, idx) => <li key={idx}>{q}</li>)}
                      </ul>
                    </div>
                  )}
                </article>
              ))
            )}
          </div>
        </section>

        <section className="lg:col-span-5 flex flex-col h-[750px] rounded-xl border border-slate-800 bg-slate-900/70 overflow-hidden shadow-lg">
          <div className="p-4 border-b border-slate-800 bg-slate-900/90 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-emerald-400" />
              <h2 className="text-sm font-semibold text-white">Live Call Copilot</h2>
            </div>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-700/50 text-emerald-300">
              Low-Latency Active
            </span>
          </div>
          <div className="flex-1 p-4 overflow-y-auto space-y-4">
            {chatMessages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-500 space-y-2">
                <ShieldAlert className="w-8 h-8 text-slate-600 mb-1" />
                <p className="text-xs">Type a customer objection to test tiered model routing.</p>
              </div>
            ) : (
              chatMessages.map((msg, index) => (
                <div key={index} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
                  <div className={`max-w-[85%] rounded-lg p-3 text-xs leading-relaxed ${msg.role === "user" ? "bg-emerald-600 text-white" : "bg-slate-950 border border-slate-800 text-slate-200"}`}>
                    {msg.content}
                  </div>
                  {msg.telemetry && (
                    <div className="mt-1.5 flex items-center gap-2 font-mono text-[10px] text-slate-400 bg-slate-950/80 px-2 py-0.5 rounded border border-slate-800">
                      <span className="text-emerald-400 font-semibold">{msg.telemetry.intent}</span>
                      <span>•</span>
                      <span>Routed to {msg.telemetry.model.split("/").pop()}</span>
                      <span>•</span>
                      <span className="flex items-center gap-0.5">
                        <Clock className="w-2.5 h-2.5" /> {msg.telemetry.totalLatency}s
                      </span>
                    </div>
                  )}
                </div>
              ))
            )}
            {isCopilotTyping && (
              <div className="flex items-center gap-2 font-mono text-xs text-slate-500 italic">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
                Nemotron Nano triaging query...
              </div>
            )}
          </div>
          <form onSubmit={handleSendMessage} className="p-3 border-t border-slate-800 bg-slate-900/90 flex gap-2">
            <input type="text" value={inputQuery} onChange={(e) => setInputQuery(e.target.value)} placeholder="Live prospect objection..." className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition font-sans" />
            <button type="submit" disabled={isCopilotTyping || !inputQuery.trim()} className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-3 py-2 rounded-lg transition text-xs flex items-center justify-center">
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}