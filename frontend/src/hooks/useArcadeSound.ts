import { useRef, useState } from "react";

/**
 * The landing page's arcade sound: short synthesized square-wave blips
 * from the Web Audio API. No audio files, so it works fully offline. Off
 * by default; the visitor opts in with the speaker button.
 */
export function useArcadeSound() {
  const [enabled, setEnabled] = useState(false);
  const contextRef = useRef<AudioContext | null>(null);

  const play = (frequency = 520) => {
    if (!enabled || typeof window === "undefined") return;
    const Ctor: typeof AudioContext | undefined =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    const context = contextRef.current ?? new Ctor();
    contextRef.current = context;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "square";
    oscillator.frequency.setValueAtTime(frequency, context.currentTime);
    gain.gain.setValueAtTime(0.025, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.07);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.07);
  };

  return { enabled, setEnabled, play };
}
