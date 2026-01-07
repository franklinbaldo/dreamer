
import React, { useState, useRef } from 'react';
import { GeminiService } from './geminiService';
import { AppState, Scene, Storyboard, VisualElement } from './types';
import { 
  Music, Upload, Play, Pause, RefreshCcw, 
  Image as ImageIcon, Loader2, AlertCircle, 
  Clock, Sparkles, Palette, Users, Layers
} from 'lucide-react';

const App: React.FC = () => {
  const [state, setState] = useState<AppState>(AppState.IDLE);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [storyboard, setStoryboard] = useState<Storyboard | null>(null);
  const [currentSceneIndex, setCurrentSceneIndex] = useState<number>(0);
  const [progress, setProgress] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const geminiRef = useRef<GeminiService>(new GeminiService());

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.type.startsWith('audio/')) {
        setError('Please upload a valid audio file.');
        return;
      }
      setAudioFile(file);
      setAudioUrl(URL.createObjectURL(file));
      setError(null);
    }
  };

  const processAudio = async () => {
    if (!audioFile) return;

    try {
      setState(AppState.ANALYZING);
      setError(null);
      setProgress(5);

      const reader = new FileReader();
      const base64Promise = new Promise<string>((resolve) => {
        reader.onload = () => resolve((reader.result as string).split(',')[1]);
        reader.readAsDataURL(audioFile);
      });
      const base64 = await base64Promise;
      
      const sb = await geminiRef.current.analyzeAudio(base64, audioFile.type);
      setStoryboard(sb);

      // --- PHASE 2: GENERATE ELEMENT REFERENCES ---
      setState(AppState.DESIGNING_ELEMENTS);
      const updatedElements: VisualElement[] = [];
      for (let i = 0; i < sb.production_design.recurring_elements.length; i++) {
        const el = sb.production_design.recurring_elements[i];
        setProgress(Math.round(((i + 1) / sb.production_design.recurring_elements.length) * 100));
        const prompt = `Production Design: Element Reference Sheet. 
        Style: ${sb.production_design.art_style}. 
        Subject: ${el.name}. 
        Description: ${el.description}. 
        Show only this subject against a neutral background for reference.`;
        
        const imageUrl = await geminiRef.current.generateImage(prompt);
        updatedElements.push({ ...el, imageUrl });
        // Live update storyboard state to show element images as they appear
        setStoryboard(prev => prev ? {
          ...prev,
          production_design: { ...prev.production_design, recurring_elements: updatedElements }
        } : null);
      }

      // --- PHASE 3: GENERATE COHERENT SCENES ---
      setState(AppState.GENERATING_IMAGES);
      const refImages = updatedElements.map(e => e.imageUrl).filter(Boolean) as string[];
      const updatedScenes: Scene[] = [];
      const total = sb.scenes.length;

      for (let i = 0; i < total; i++) {
        const scene = sb.scenes[i];
        setProgress(Math.round(((i + 1) / total) * 100));
        
        const scenePrompt = `Using the provided visual references for character/element consistency and following the style "${sb.production_design.art_style}", create this scene: ${scene.visual_prompt}. Maintain perfect visual coherence with the references.`;
        
        const imageUrl = await geminiRef.current.generateImage(scenePrompt, refImages);
        updatedScenes.push({ ...scene, imageUrl });
        
        setStoryboard(prev => prev ? { ...prev, scenes: [...updatedScenes, ...sb.scenes.slice(i + 1)] } : null);
      }

      setState(AppState.READY);
    } catch (err: any) {
      setError(err.message || "An error occurred.");
      setState(AppState.ERROR);
    }
  };

  const reset = () => {
    setState(AppState.IDLE);
    setAudioFile(null);
    setAudioUrl(null);
    setStoryboard(null);
    setCurrentSceneIndex(0);
    setProgress(0);
    setError(null);
  };

  return (
    <div className="min-h-screen p-4 md:p-8 flex flex-col items-center justify-center">
      <div className="max-w-6xl w-full flex flex-col gap-8">
        <header className="text-center space-y-2">
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight">
            Sonic<span className="gradient-text">Vision</span> Studio
          </h1>
          <p className="text-slate-400 text-lg">Consistent visual storytelling with Image-to-Image reference.</p>
        </header>

        <main className="glass rounded-3xl p-6 md:p-10 shadow-2xl relative overflow-hidden">
          {/* Progress Overlays */}
          {[AppState.ANALYZING, AppState.DESIGNING_ELEMENTS, AppState.GENERATING_IMAGES].includes(state) && (
            <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-slate-900/95 backdrop-blur-md">
              <div className="bg-slate-800 p-8 rounded-2xl border border-slate-700 shadow-xl flex flex-col items-center gap-6 max-w-lg w-full">
                <div className="relative">
                   <Loader2 className="w-16 h-16 text-blue-500 animate-spin" />
                   <div className="absolute inset-0 flex items-center justify-center text-xs font-bold text-white">
                     {progress}%
                   </div>
                </div>
                <div className="text-center space-y-2">
                  <h3 className="text-2xl font-semibold">
                    {state === AppState.ANALYZING && 'Mapping Production Structure...'}
                    {state === AppState.DESIGNING_ELEMENTS && 'Generating Reference Assets...'}
                    {state === AppState.GENERATING_IMAGES && 'Executing Final Production...'}
                  </h3>
                  <p className="text-slate-400 text-sm">
                    {state === AppState.DESIGNING_ELEMENTS ? 'Creating visual blueprints for characters and objects to ensure consistency.' : 'Synthesizing final frames using reference blueprints.'}
                  </p>
                </div>
                <div className="w-full bg-slate-700 h-2 rounded-full overflow-hidden">
                  <div className="bg-gradient-to-r from-blue-500 to-purple-500 h-full transition-all duration-500" style={{ width: `${progress}%` }} />
                </div>
              </div>
            </div>
          )}

          {state === AppState.IDLE && (
            <div className="flex flex-col items-center py-12 gap-8">
              <div className="w-24 h-24 rounded-full bg-slate-800 flex items-center justify-center border-2 border-dashed border-slate-600">
                <Music className="w-10 h-10 text-slate-400" />
              </div>
              <div className="text-center space-y-4">
                <h2 className="text-2xl font-bold">Synchronized Multi-Reference Production</h2>
                <p className="text-slate-400 max-w-md">Our engine first designs your characters and motifs, then uses those images to guide every scene for perfect coherence.</p>
                <label className="cursor-pointer bg-blue-600 hover:bg-blue-500 text-white font-semibold py-3 px-10 rounded-full transition-all flex items-center gap-2 shadow-lg mt-4 active:scale-95 inline-flex">
                  <Upload className="w-5 h-5" /> Select MP3
                  <input type="file" accept="audio/mp3,audio/mpeg" className="hidden" onChange={handleFileUpload} />
                </label>
                {audioFile && <p className="text-blue-400 font-medium">{audioFile.name}</p>}
              </div>
              {audioFile && (
                <button onClick={processAudio} className="bg-white text-slate-900 font-bold py-4 px-14 rounded-2xl shadow-xl active:scale-95 flex items-center gap-2">
                  <Sparkles className="w-6 h-6 text-blue-600" /> Start Production
                </button>
              )}
            </div>
          )}

          {state === AppState.ERROR && (
            <div className="flex flex-col items-center py-12 gap-6">
              <AlertCircle className="w-12 h-12 text-red-500" />
              <p className="text-red-400 font-bold">{error}</p>
              <button onClick={reset} className="bg-slate-800 text-white px-6 py-2 rounded-lg border border-slate-700">Try Again</button>
            </div>
          )}

          {state === AppState.READY && storyboard && (
            <div className="flex flex-col gap-10 animate-in fade-in duration-1000">
              <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                {/* References Column */}
                <div className="lg:col-span-1 space-y-6">
                  <div className="bg-slate-800/40 border border-slate-700 p-5 rounded-2xl space-y-6">
                    <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2 border-b border-slate-700 pb-2">
                      <Layers className="w-4 h-4" /> Visual Blueprints
                    </h3>
                    <div className="space-y-4">
                      {storyboard.production_design.recurring_elements.map((el, idx) => (
                        <div key={idx} className="space-y-2">
                          <p className="text-xs font-bold text-blue-400">{el.name}</p>
                          {el.imageUrl ? (
                            <img src={el.imageUrl} className="w-full aspect-square object-cover rounded-lg border border-slate-600 shadow-lg" alt={el.name} />
                          ) : (
                            <div className="w-full aspect-square bg-slate-900 rounded-lg animate-pulse" />
                          )}
                          <p className="text-[10px] text-slate-500 leading-tight">{el.description}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Player Column */}
                <div className="lg:col-span-3 space-y-8">
                  <div className="relative aspect-video rounded-3xl overflow-hidden bg-slate-950 border border-slate-800 shadow-2xl">
                    {storyboard.scenes[currentSceneIndex]?.imageUrl ? (
                      <img key={currentSceneIndex} src={storyboard.scenes[currentSceneIndex].imageUrl} className="w-full h-full object-cover animate-in fade-in duration-1000" alt="" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-slate-700">
                        <Loader2 className="animate-spin w-12 h-12" />
                      </div>
                    )}
                    <div className="absolute bottom-0 inset-x-0 p-8 bg-gradient-to-t from-black via-black/40 to-transparent">
                      <div className="flex items-end gap-4">
                        <div className="bg-blue-600 px-3 py-1.5 rounded-lg text-white text-sm font-mono font-bold">{Math.floor(storyboard.scenes[currentSceneIndex].timestamp / 60)}:{(storyboard.scenes[currentSceneIndex].timestamp % 60).toFixed(1).toString().padStart(4, '0')}</div>
                        <h4 className="text-2xl font-bold text-white drop-shadow-lg">{storyboard.scenes[currentSceneIndex].description}</h4>
                      </div>
                    </div>
                  </div>

                  <div className="bg-slate-800/80 p-8 rounded-3xl border border-slate-700 flex flex-col gap-6">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-6">
                        <button onClick={() => audioRef.current?.paused ? audioRef.current?.play() : audioRef.current?.pause()} className="w-16 h-16 bg-white text-slate-950 rounded-full flex items-center justify-center shadow-xl hover:scale-105 active:scale-95">
                          {audioRef.current?.paused ? <Play className="w-8 h-8 fill-current translate-x-1" /> : <Pause className="w-8 h-8 fill-current" />}
                        </button>
                        <div>
                          <h3 className="font-bold text-xl text-white">{storyboard.title}</h3>
                          <div className="flex items-center gap-2 text-blue-400 text-sm font-bold">
                            <Sparkles className="w-4 h-4" /> Multi-Ref Coherence Active
                          </div>
                        </div>
                      </div>
                      <button onClick={reset} className="text-slate-400 p-3 bg-slate-700/50 rounded-xl border border-slate-600"><RefreshCcw className="w-4 h-4" /></button>
                    </div>
                    <audio ref={audioRef} src={audioUrl || ""} className="w-full h-12" onTimeUpdate={() => {
                      if (!audioRef.current || !storyboard) return;
                      const time = audioRef.current.currentTime;
                      const idx = storyboard.scenes.reduce((p, c, i) => time >= c.timestamp ? i : p, 0);
                      if (idx !== currentSceneIndex) setCurrentSceneIndex(idx);
                    }} controls />
                  </div>
                </div>
              </div>

              {/* Storyboard Reel */}
              <div className="space-y-4">
                <h3 className="text-xl font-bold flex items-center gap-2"><ImageIcon className="w-6 h-6 text-purple-400" /> Production Reel</h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-4">
                  {storyboard.scenes.map((scene, idx) => (
                    <button key={idx} onClick={() => { if (audioRef.current) audioRef.current.currentTime = scene.timestamp; }}
                      className={`relative aspect-video rounded-xl overflow-hidden border-2 transition-all ${currentSceneIndex === idx ? 'border-blue-500 scale-105 z-10' : 'border-slate-800 opacity-60'}`}>
                      {scene.imageUrl && <img src={scene.imageUrl} className="w-full h-full object-cover" alt="" />}
                      <div className="absolute top-1 left-1 bg-blue-600/90 px-2 py-0.5 rounded text-[10px] text-white font-bold">{scene.timestamp.toFixed(1)}s</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

export default App;
