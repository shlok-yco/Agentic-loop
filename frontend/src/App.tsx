import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import ReactECharts from "echarts-for-react";
import { MessageSquare, Upload, Play, Terminal, Database, Loader2, Bot, FileText, ChevronLeft, ChevronRight } from "lucide-react";

const API_BASE = "http://localhost:5000";

interface LogEntry {
  event_type: string;
  division?: string;
  node?: string;
  tool_calls?: any[];
  tool_result?: string;
  content?: string;
  insights?: any[];
  status?: string;
  generated_artifacts?: Record<string, string>;
}

interface ExplorableArtifact {
  path: string;
  name: string;
  content: string | null;
}

interface ChatRun {
  runId: string;
  query: string;
  status: string;
  logs: LogEntry[];
  insights: any[];
  echartsOptions: Record<string, any>;
  artifacts: Record<string, string>;
}

function ChartGroup({ opt }: { opt: any }) {
  const [variationIndex, setVariationIndex] = useState(0);

  const variations = opt.variations || [opt];
  const currentVariation = variations[variationIndex];

  const echartsOption = currentVariation.echarts_option || currentVariation;
  const reasoning = currentVariation.reasoning || opt.reasoning;
  const takeaway = currentVariation.expected_takeaway || opt.expected_takeaway;
  const title = opt.title;

  return (
    <div className="flex flex-col mb-8 border border-gray-200 rounded-2xl overflow-hidden bg-white shadow-md">
      <div className="bg-gray-50 p-3 border-b border-gray-200 flex items-center justify-between">
        <h3 className="font-bold text-gray-800 text-sm">{title || "Visualization"}</h3>
        {variations.length > 1 && (
          <div className="flex items-center gap-1">
            <button onClick={() => setVariationIndex(prev => Math.max(0, prev - 1))} disabled={variationIndex === 0} className="p-1 hover:bg-gray-200 rounded disabled:opacity-50">&lt;</button>
            <span className="text-xs text-gray-500">{variationIndex + 1}/{variations.length}</span>
            <button onClick={() => setVariationIndex(prev => Math.min(variations.length - 1, prev + 1))} disabled={variationIndex === variations.length - 1} className="p-1 hover:bg-gray-200 rounded disabled:opacity-50">&gt;</button>
          </div>
        )}
      </div>
      <div className="p-6">
        <div className="h-80 md:h-96 w-full mb-6 border border-gray-100 rounded-xl p-2 bg-white shadow-inner">
          <ReactECharts option={echartsOption} notMerge={true} style={{ height: '100%', width: '100%' }} />
        </div>
        <div className="text-sm text-gray-800 space-y-4 bg-emerald-50/30 p-5 rounded-xl border border-emerald-100">
          {currentVariation.chart_type && (
            <div className="inline-block px-3 py-1 bg-emerald-100 text-emerald-800 rounded-md text-xs font-bold uppercase tracking-wider shadow-sm">
              Chart Type: {currentVariation.chart_type}
            </div>
          )}
          {reasoning && (
            <div className="leading-relaxed text-gray-700">
              <strong className="text-gray-900 text-base mb-1 flex items-center gap-2">
                <Bot size={16} className="text-emerald-600" /> Reasoning
              </strong> 
              <p className="ml-6">{reasoning}</p>
            </div>
          )}
          {takeaway && (
            <div className="leading-relaxed text-gray-700">
              <strong className="text-gray-900 text-base mb-1 flex items-center gap-2">
                <FileText size={16} className="text-emerald-600" /> Expected Takeaway
              </strong>
              <p className="ml-6">{takeaway}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [dataPath, setDataPath] = useState<string>("");
  const [query, setQuery] = useState("");
  
  const [runs, setRuns] = useState<ChatRun[]>([]);
  const [currentRunId, setCurrentRunId] = useState<string>("");

  const [scripts, setScripts] = useState<ExplorableArtifact[]>([]);
  const [dataArtifacts, setDataArtifacts] = useState<ExplorableArtifact[]>([]);
  const [scriptIndex, setScriptIndex] = useState(0);
  const [dataIndex, setDataIndex] = useState(0);

  const logsEndRef = useRef<HTMLDivElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const scriptsRef = useRef(scripts);
  useEffect(() => { scriptsRef.current = scripts; }, [scripts]);

  const dataArtifactsRef = useRef(dataArtifacts);
  useEffect(() => { dataArtifactsRef.current = dataArtifacts; }, [dataArtifacts]);

  // Auto-scroll chat to bottom only when a new run is added
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [runs.length]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      setFile(selectedFile);
      const formData = new FormData();
      formData.append("file", selectedFile);
      try {
        const res = await axios.post(`${API_BASE}/upload`, formData);
        setDataPath(res.data.file_path);
      } catch (err) {
        console.error("Upload failed", err);
        alert("Upload failed");
      }
    }
  };

  const startRun = async () => {
    if (!dataPath || !query.trim()) return;
    const newRunId = "RUN-" + Math.random().toString(36).substring(2, 10).toUpperCase();
    
    const newRun: ChatRun = {
      runId: newRunId,
      query,
      status: "RUNNING",
      logs: [],
      insights: [],
      echartsOptions: {},
      artifacts: {},
    };

    setRuns(prev => [...prev, newRun]);
    setCurrentRunId(newRunId);
    setQuery("");
    setScripts([]);
    setDataArtifacts([]);
    setScriptIndex(0);
    setDataIndex(0);
    setIsSidebarOpen(true);

    try {
      axios.post(`${API_BASE}/run`, {
        user_query: query,
        data_path: dataPath,
        run_id: newRunId,
      });
    } catch (err) {
      console.error(err);
    }
  };

  const fetchArtifact = async (path: string, setter: (val: string) => void) => {
    try {
      const res = await axios.get(`${API_BASE}/artifact?path=${encodeURIComponent(path)}`);
      if (typeof res.data === 'object') {
        setter(JSON.stringify(res.data, null, 2));
      } else {
        setter(res.data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    
    if (currentRunId) {
      interval = setInterval(async () => {
        try {
          const res = await axios.get(`${API_BASE}/status/${currentRunId}`);
          const updatedLogs = res.data.project_log || [];
          const currentArtifacts = res.data.artifact_paths || {};
          
          for (const [name, path] of Object.entries(currentArtifacts)) {
            const p = path as string;
            if (p.endsWith('.py')) {
               if (!scriptsRef.current.find(s => s.path === p)) {
                  setScripts(prev => [...prev, { path: p, name, content: null }]);
                  fetchArtifact(p, (content) => {
                     setScripts(prev => prev.map(s => s.path === p ? { ...s, content } : s));
                  });
               }
            } else if (p.endsWith('.csv') || p.endsWith('.json')) {
               if (!dataArtifactsRef.current.find(d => d.path === p)) {
                  setDataArtifacts(prev => [...prev, { path: p, name, content: null }]);
                  fetchArtifact(p, (content) => {
                     setDataArtifacts(prev => prev.map(d => d.path === p ? { ...d, content } : d));
                  });
               }
            }
          }

          updatedLogs.forEach((log: any) => {
            if (log.tool_result) {
              try {
                const tr = JSON.parse(log.tool_result);
                if (tr.script_path) {
                  const p = tr.script_path;
                  const name = p.split('/').pop() || 'script.py';
                  if (!scriptsRef.current.find(s => s.path === p)) {
                    setScripts(prev => [...prev, { path: p, name, content: tr.script_code || null }]);
                    if (!tr.script_code) {
                      fetchArtifact(p, (content) => {
                         setScripts(prev => prev.map(s => s.path === p ? { ...s, content } : s));
                      });
                    }
                  }
                }
              } catch (e) {
                // ignore
              }
            }
          });

          let newStatus = res.data.pipeline_stage;
          if (newStatus === "COMPLETED" || newStatus === "FAILED" || newStatus === "visualization_completed") {
            clearInterval(interval);
            const finalRes = await axios.get(`${API_BASE}/result/${currentRunId}`);
            setRuns(prev => prev.map(r => r.runId === currentRunId ? {
                ...r,
                status: newStatus === "FAILED" ? "FAILED" : "COMPLETED",
                logs: finalRes.data.project_log && finalRes.data.project_log.length > 0 ? finalRes.data.project_log : updatedLogs,
                insights: finalRes.data.insights || [],
                echartsOptions: finalRes.data.echarts_options || {},
                artifacts: finalRes.data.artifact_paths || {},
            } : r));
          } else {
            setRuns(prev => prev.map(r => r.runId === currentRunId ? {
                ...r,
                status: newStatus && newStatus !== "UNKNOWN" ? newStatus : r.status,
                logs: updatedLogs,
            } : r));
          }
        } catch (err) {
          console.error("Polling error", err);
        }
      }, 2000);
    }
    
    return () => clearInterval(interval);
  }, [currentRunId]);

  const hasArtifacts = scripts.length > 0 || dataArtifacts.length > 0;

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 font-sans">
      {/* Left Sidebar */}
      <div className="w-64 bg-gray-100 border-r border-gray-200 p-4 flex flex-col z-20">
        <h2 className="text-lg font-bold text-gray-800 mb-6 flex items-center gap-2">
          <MessageSquare size={20} /> Chats
        </h2>
        <div className="flex-1 overflow-y-auto space-y-2">
          {runs.map((r) => (
            <div key={r.runId} className="p-3 bg-white rounded-lg shadow-sm border border-gray-200 cursor-pointer text-sm font-medium hover:bg-gray-50 transition truncate">
              {r.query}
            </div>
          ))}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col h-full overflow-hidden bg-white relative">
        <header className="bg-white/80 backdrop-blur-md border-b border-gray-100 p-4 flex justify-between items-center z-10 sticky top-0">
          <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <Bot className="text-emerald-600" /> Agentic Data Analyst
          </h1>
          <div className="flex items-center gap-4">
            <label className="cursor-pointer bg-white border border-gray-200 text-gray-700 px-4 py-2 rounded-full hover:bg-gray-50 transition flex items-center gap-2 text-sm font-medium shadow-sm">
              <Upload size={16} className="text-emerald-600" /> {file ? file.name : "Upload Dataset"}
              <input type="file" accept=".csv" className="hidden" onChange={handleUpload} />
            </label>
            {hasArtifacts && (
               <button 
                 onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                 className="flex items-center gap-2 px-3 py-2 bg-emerald-50 text-emerald-700 rounded-lg hover:bg-emerald-100 transition text-sm font-medium border border-emerald-200"
               >
                 <Terminal size={16} />
                 {isSidebarOpen ? "Hide Artifacts" : "Show Artifacts"}
               </button>
            )}
          </div>
        </header>

        {/* Chat History */}
        <div className="flex-1 overflow-y-auto p-4 md:p-8 space-y-8 pb-32">
          {runs.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-gray-400 max-w-md mx-auto text-center space-y-4">
               <Bot size={48} className="text-emerald-200" />
               <h2 className="text-2xl font-bold text-gray-700">How can I help you analyze data today?</h2>
               <p className="text-sm">Upload a CSV file and ask me to clean, summarize, or extract insights from it.</p>
            </div>
          ) : (
            runs.map((run) => (
              <div key={run.runId} className="flex flex-col space-y-6 w-full max-w-4xl mx-auto">
                {/* User Bubble */}
                <div className="flex justify-end">
                  <div className="bg-emerald-600 text-white px-5 py-3.5 rounded-2xl rounded-tr-sm max-w-[85%] shadow-sm text-sm md:text-base leading-relaxed">
                    {run.query}
                  </div>
                </div>
                
                {/* Assistant Bubble */}
                <div className="flex justify-start">
                  <div className="bg-gray-50 border border-gray-100 text-gray-800 px-6 py-5 rounded-2xl rounded-tl-sm max-w-[95%] w-full shadow-sm">
                    <div className="flex items-center gap-2 mb-4 font-bold text-emerald-800">
                       <Bot size={20} />
                       <span>Data Agent</span>
                    </div>
                    
                    {/* Thinking block */}
                    {run.logs.length > 0 && (
                      <details className="mb-4 bg-white rounded-xl border border-gray-200 overflow-hidden text-xs shadow-sm" open={run.status === "RUNNING"}>
                        <summary className="cursor-pointer p-3 font-medium text-gray-600 hover:bg-gray-50 transition flex items-center gap-2 outline-none">
                           {run.status === 'RUNNING' ? <Loader2 className="w-4 h-4 animate-spin text-emerald-600" /> : <Terminal className="w-4 h-4 text-emerald-600" />}
                           {run.status === 'RUNNING' ? 'Agent is thinking...' : 'View thinking process'}
                        </summary>
                        <div className="p-4 font-mono border-t border-gray-100 max-h-64 overflow-y-auto bg-gray-50/50">
                           {run.logs.map((l, i) => {
                              // Custom rendering logic
                              if (l.division === "Supervisor" && l.event_type === "PLANNING" && l.tool_calls) {
                                return l.tool_calls.map((tc, j) => {
                                  if (tc.name === "lead_data_engineer") {
                                    return (
                                      <div key={`${i}-${j}`} className="mb-3 border-l-2 border-emerald-200 pl-3">
                                        <span className="font-bold text-emerald-700 tracking-wide uppercase text-[10px]">[SUPERVISOR] PLANNING</span>
                                        <p className="mt-1 text-gray-700 whitespace-pre-wrap font-semibold">Calling data engineering swarm for: {tc.args?.summary}</p>
                                      </div>
                                    )
                                  } else if (tc.name === "lead_analyst") {
                                    return (
                                      <div key={`${i}-${j}`} className="mb-3 border-l-2 border-emerald-200 pl-3">
                                        <span className="font-bold text-emerald-700 tracking-wide uppercase text-[10px]">[SUPERVISOR] PLANNING</span>
                                        <p className="mt-1 text-gray-700 whitespace-pre-wrap font-semibold">Calling data analytics swarm for: {tc.args?.summary}</p>
                                      </div>
                                    )
                                  }
                                  return null;
                                })
                              }

                              if (l.division === "Data Engineer" && l.event_type === "THINKING" && l.tool_calls) {
                                return l.tool_calls.map((tc, j) => {
                                  if (tc.name === "submit_engineer_report") {
                                    return (
                                      <div key={`${i}-${j}`} className="mb-3 border-l-2 border-emerald-200 pl-3">
                                        <span className="font-bold text-emerald-700 tracking-wide uppercase text-[10px]">[DATA ENGINEER] REPORT</span>
                                        <p className="mt-1 text-gray-700 whitespace-pre-wrap italic">{tc.args?.summary}</p>
                                      </div>
                                    )
                                  }
                                  return (
                                    <div key={`${i}-${j}`} className="mb-3 border-l-2 border-emerald-200 pl-3">
                                      <span className="font-bold text-emerald-700 tracking-wide uppercase text-[10px]">[DATA ENGINEER] ACTION</span>
                                      <div className="mt-1 text-emerald-600">
                                        <span className="font-semibold">Tool call:</span> {tc.name}
                                      </div>
                                    </div>
                                  )
                                })
                              }

                              if (l.division === "Data Analyst" && l.event_type === "THINKING" && l.tool_calls) {
                                return l.tool_calls.map((tc, j) => {
                                  if (tc.name === "submit_analyst_report") {
                                    return (
                                      <div key={`${i}-${j}`} className="mb-3 border-l-2 border-emerald-200 pl-3">
                                        <span className="font-bold text-emerald-700 tracking-wide uppercase text-[10px]">[DATA ANALYST] REPORT</span>
                                        <p className="mt-1 text-gray-700 whitespace-pre-wrap italic">{tc.args?.execution_summary || tc.args?.summary}</p>
                                      </div>
                                    )
                                  }

                                  let parsedArgs: any = {};
                                  if (tc.args) {
                                    parsedArgs = { ...tc.args };
                                    Object.keys(parsedArgs).forEach(k => {
                                      if (typeof parsedArgs[k] === 'string' && (parsedArgs[k].startsWith('{') || parsedArgs[k].startsWith('['))) {
                                        try { parsedArgs[k] = JSON.parse(parsedArgs[k]); } catch(e) {}
                                      }
                                    });
                                  }

                                  if (tc.name === "write_artifact" && parsedArgs.artifact_type === "business_objectives") {
                                    return (
                                      <div key={`${i}-${j}`} className="mb-3 border-l-2 border-emerald-200 pl-3">
                                        <span className="font-bold text-emerald-700 tracking-wide uppercase text-[10px]">[DATA ANALYST] ACTION</span>
                                        <div className="mt-1 text-emerald-600">
                                          <span className="font-semibold">Tool call:</span> {tc.name}
                                        </div>
                                        <div className="mt-2 text-gray-700 text-xs space-y-2">
                                          <div className="font-bold">Business Objectives:</div>
                                          <ul className="list-decimal pl-5 space-y-2">
                                            {Array.isArray(parsedArgs.business_objectives) && parsedArgs.business_objectives.map((obj: any, idx: number) => (
                                              <li key={idx}>
                                                <span className="font-medium">{obj.objective_statement}</span>
                                                <br/>
                                                <span className="text-gray-500 italic mt-1 block">Reasoning: {obj.business_rationale}</span>
                                              </li>
                                            ))}
                                          </ul>
                                        </div>
                                      </div>
                                    )
                                  }
                                  
                                  let summaryText = parsedArgs.summary || parsedArgs.execution_summary || "Executing data analysis task...";
                                  
                                  return (
                                    <div key={`${i}-${j}`} className="mb-3 border-l-2 border-emerald-200 pl-3">
                                      <span className="font-bold text-emerald-700 tracking-wide uppercase text-[10px]">[DATA ANALYST] ACTION</span>
                                      <div className="mt-1 text-emerald-600">
                                        <span className="font-semibold">Tool call:</span> {tc.name}
                                        <div className="text-gray-700 text-xs italic mt-1">{summaryText}</div>
                                      </div>
                                    </div>
                                  )
                                })
                              }

                              // Fallback for actions and content
                              return (
                                <div key={i} className="mb-3 border-l-2 border-emerald-200 pl-3">
                                  <span className="font-bold text-emerald-700 tracking-wide uppercase text-[10px]">[{l.division || "SYSTEM"}] {l.event_type}</span>
                                  {l.content && !l.content.includes("```json") && <p className="mt-1 text-gray-700 whitespace-pre-wrap">{l.content}</p>}
                                </div>
                              )
                           })}
                           {run.status === 'RUNNING' && <div ref={logsEndRef} />}
                        </div>
                      </details>
                    )}

                    {/* Results */}
                    {run.status === "FAILED" && (
                      <div className="text-red-500 font-medium">Pipeline execution failed. Please check the logs.</div>
                    )}
                    
                    {run.status === "COMPLETED" && (
                       <div className="space-y-8 mt-6">
                         {(() => {
                            const renderedCharts = new Set<string>();
                            const chartsEntries = Object.entries(run.echartsOptions)
                               .sort(([, a], [, b]) => {
                                  const pA = a.priority !== undefined ? a.priority : 999;
                                  const pB = b.priority !== undefined ? b.priority : 999;
                                  return pA - pB;
                               });

                            return (
                              <>
                                {run.insights.length > 0 && run.insights.map((ins, idx) => {
                                   const chartsToRender = chartsEntries.filter(([key, opt]) => {
                                     if (renderedCharts.has(key)) return false;
                                     const supported = Array.isArray(opt.supported_insights) ? opt.supported_insights : [];
                                     const lastSupportedInsight = supported.map((sId: string) => run.insights.findIndex(i => i.insight_id === sId || (i.insight_id && sId.includes(i.insight_id))))
                                                                           .filter((i: number) => i !== -1)
                                                                           .sort((a: number, b: number) => b - a)[0];
                                     return lastSupportedInsight === idx;
                                   });
                                   
                                   chartsToRender.forEach(([key]) => renderedCharts.add(key));

                                   return (
                                     <React.Fragment key={`ins-group-${idx}`}>
                                       {chartsToRender.length > 0 && (
                                         <div className="grid grid-cols-1 gap-8 mb-8">
                                           {chartsToRender.map(([key, opt]) => (
                                             <ChartGroup key={key} opt={opt} />
                                           ))}
                                         </div>
                                       )}
                                       <div className="space-y-4 mb-4 pb-4 border-b border-gray-100">
                                         <div className="prose text-sm md:text-base text-gray-800">
                                           <h4 className="font-bold text-lg mb-2 text-gray-900">{ins.title}</h4>
                                           <p className="leading-relaxed">{ins.finding}</p>
                                           {ins.recommendation && (
                                             <div className="mt-3 bg-emerald-50 text-emerald-800 p-3 rounded-lg text-sm border border-emerald-100">
                                               <strong className="block mb-1">Recommendation:</strong> {ins.recommendation}
                                             </div>
                                           )}
                                         </div>
                                       </div>
                                     </React.Fragment>
                                   );
                                })}
                                
                                {chartsEntries.filter(([key]) => !renderedCharts.has(key)).length > 0 && (
                                   <div className="grid grid-cols-1 gap-8 mt-8">
                                     {chartsEntries.filter(([key]) => !renderedCharts.has(key)).map(([key, opt]) => (
                                        <ChartGroup key={key} opt={opt} />
                                     ))}
                                   </div>
                                )}
                              </>
                            );
                         })()}
                       </div>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Input Area (Floating style) */}
        <div className="absolute bottom-0 w-full bg-gradient-to-t from-white via-white to-transparent pt-10 pb-6 px-4 md:px-8">
          <div className="max-w-4xl mx-auto relative flex items-center bg-white border border-gray-300 rounded-2xl shadow-lg focus-within:ring-2 focus-within:ring-emerald-500 focus-within:border-emerald-500 transition-all overflow-hidden">
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Message Agentic Data Analyst..."
              className="flex-1 bg-transparent px-6 py-4 focus:outline-none text-gray-800 placeholder-gray-400"
              onKeyDown={e => {
                if (e.key === 'Enter') startRun();
              }}
              disabled={!dataPath || runs.some(r => r.status === 'RUNNING')}
            />
            <button
              onClick={startRun}
              disabled={runs.some(r => r.status === 'RUNNING') || !dataPath || !query.trim()}
              className="bg-emerald-600 text-white w-10 h-10 rounded-xl hover:bg-emerald-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition flex items-center justify-center mr-2 shadow-sm"
            >
              {runs.some(r => r.status === 'RUNNING') ? <Loader2 className="animate-spin w-5 h-5" /> : <Play className="w-5 h-5 ml-1" />}
            </button>
          </div>
          {!dataPath && <p className="text-center text-xs text-gray-500 mt-3 flex items-center justify-center gap-1"><FileText size={14}/> Please upload a dataset to begin.</p>}
        </div>
      </div>

      {/* Right Sidebar (Generated Code & Data) */}
      {hasArtifacts && isSidebarOpen && (
        <div className="w-80 md:w-96 bg-white border-l border-gray-200 flex flex-col shadow-xl z-20 transition-all">
          <div className="h-1/2 flex flex-col border-b border-gray-200">
            <div className="bg-gray-50 text-gray-800 p-3 font-bold text-sm flex items-center justify-between border-b border-gray-200">
              <div className="flex items-center gap-2">
                <Terminal size={16} className="text-emerald-600" /> 
                {scripts.length > 0 ? scripts[scriptIndex]?.name : "Generated Code"}
              </div>
              {scripts.length > 1 && (
                <div className="flex items-center gap-1">
                  <button onClick={() => setScriptIndex(prev => Math.max(0, prev - 1))} disabled={scriptIndex === 0} className="p-1 hover:bg-gray-200 rounded disabled:opacity-50">&lt;</button>
                  <span className="text-xs text-gray-500">{scriptIndex + 1}/{scripts.length}</span>
                  <button onClick={() => setScriptIndex(prev => Math.min(scripts.length - 1, prev + 1))} disabled={scriptIndex === scripts.length - 1} className="p-1 hover:bg-gray-200 rounded disabled:opacity-50">&gt;</button>
                </div>
              )}
            </div>
            <div className="flex-1 p-4 bg-[#1e1e1e] text-[#d4d4d4] font-mono text-xs overflow-auto">
              <pre className="whitespace-pre-wrap">{scripts.length > 0 ? (scripts[scriptIndex]?.content || "Loading...") : "Waiting for script..."}</pre>
            </div>
          </div>
          <div className="h-1/2 flex flex-col">
            <div className="bg-gray-50 text-gray-800 p-3 font-bold text-sm flex items-center justify-between border-b border-gray-200">
              <div className="flex items-center gap-2">
                <Database size={16} className="text-emerald-600" /> 
                {dataArtifacts.length > 0 ? dataArtifacts[dataIndex]?.name : "Output Artifacts"}
              </div>
              {dataArtifacts.length > 1 && (
                <div className="flex items-center gap-1">
                  <button onClick={() => setDataIndex(prev => Math.max(0, prev - 1))} disabled={dataIndex === 0} className="p-1 hover:bg-gray-200 rounded disabled:opacity-50">&lt;</button>
                  <span className="text-xs text-gray-500">{dataIndex + 1}/{dataArtifacts.length}</span>
                  <button onClick={() => setDataIndex(prev => Math.min(dataArtifacts.length - 1, prev + 1))} disabled={dataIndex === dataArtifacts.length - 1} className="p-1 hover:bg-gray-200 rounded disabled:opacity-50">&gt;</button>
                </div>
              )}
            </div>
            <div className="flex-1 p-4 bg-gray-50 text-gray-800 font-mono text-xs overflow-auto border-t border-gray-200 shadow-inner">
              <pre className="whitespace-pre-wrap">{dataArtifacts.length > 0 ? (dataArtifacts[dataIndex]?.content || "Loading...") : "Waiting for data artifacts..."}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
