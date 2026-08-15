/**
 * Thin wrapper around the browser's Web Speech API (`SpeechRecognition`).
 *
 * Only Chromium and Safari ship an implementation — Firefox has none — so
 * `speechSupported()` lets the UI degrade gracefully (recordings still work,
 * captions just don't appear). Recognition is also a network round-trip to
 * the vendor's speech servers in Chrome, which is fine for live captions:
 * the audio is not uploaded to the app's own backend.
 */

export type Caption = {
  /** Seconds into the recording where this line started. */
  start: number
  end: number
  text: string
}

/** Options for the transcription language select — "Auto" is the empty code. */
export const RECOGNITION_LANGUAGES = [
  { code: '', label: 'Auto' },
  { code: 'en-US', label: 'English (US)' },
  { code: 'en-GB', label: 'English (UK)' },
  { code: 'hi-IN', label: 'Hindi' },
  { code: 'es-ES', label: 'Spanish' },
  { code: 'fr-FR', label: 'French' },
  { code: 'de-DE', label: 'German' },
  { code: 'it-IT', label: 'Italian' },
  { code: 'pt-BR', label: 'Portuguese (Brazil)' },
  { code: 'ja-JP', label: 'Japanese' },
  { code: 'ko-KR', label: 'Korean' },
  { code: 'zh-CN', label: 'Chinese (Simplified)' },
  { code: 'ru-RU', label: 'Russian' },
  { code: 'ar-SA', label: 'Arabic' },
  { code: 'tr-TR', label: 'Turkish' },
  { code: 'nl-NL', label: 'Dutch' },
  { code: 'pl-PL', label: 'Polish' },
  { code: 'ta-IN', label: 'Tamil' },
  { code: 'te-IN', label: 'Telugu' },
  { code: 'bn-IN', label: 'Bengali' },
  { code: 'mr-IN', label: 'Marathi' },
] as const

/**
 * Minimal shape of the Web Speech API's recognizer.
 *
 * TypeScript's DOM lib ships the *event* types but not the `SpeechRecognition`
 * interface itself (it's a WICG spec, not WHATWG), so the shape is declared
 * here against the parts we touch.
 */
type RecognitionInstance = {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}

type RecognitionCtor = { new (): RecognitionInstance }

/** Resolve the constructor across vendor prefixes, or null when unsupported. */
function recognizerCtor(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null
  const w = window as typeof window & {
    SpeechRecognition?: RecognitionCtor
    webkitSpeechRecognition?: RecognitionCtor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export function speechSupported(): boolean {
  return recognizerCtor() !== null
}

type CaptionsOptions = {
  /** BCP-47 tag; omit (or pass '') for the browser's default language. */
  lang?: string
  /** Fired for each settled phrase — commit it to the caption list. */
  onFinal: (text: string) => void
  /** Fired continuously with the still-forming phrase. */
  onInterim: (text: string) => void
}

/**
 * A running SpeechRecognition session that restarts itself across silences.
 *
 * Even with `continuous: true` the recognizer stops after a long pause, so the
 * wrapper keeps it alive until `stop()` or `abort()` is called — a recording
 * that goes quiet for a minute must not silently lose its captions.
 */
export class LiveCaptions {
  private recognition: RecognitionInstance | null
  private stopped = false
  private restarting = false

  constructor({ lang, onFinal, onInterim }: CaptionsOptions) {
    const Ctor = recognizerCtor()
    if (!Ctor) {
      this.recognition = null
      return
    }
    const recognition = new Ctor()
    recognition.continuous = true
    recognition.interimResults = true
    if (lang) recognition.lang = lang

    recognition.onresult = (event) => {
      let interim = ''
      let final = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i]
        const text = result[0].transcript
        if (result.isFinal) final += text
        else interim += text
      }
      if (final.trim()) onFinal(final.trim())
      if (interim.trim()) onInterim(interim.trim())
    }
    // A transient recognition error should not kill the captions for the rest
    // of a long recording — restart unless we're shutting down.
    recognition.onerror = () => {
      if (!this.stopped) this.restart()
    }
    recognition.onend = () => {
      if (!this.stopped) this.restart()
    }

    this.recognition = recognition
  }

  get supported(): boolean {
    return this.recognition !== null
  }

  start(): void {
    this.recognition?.start()
  }

  /** Stop listening, keeping whatever was already recognised. */
  stop(): void {
    this.stopped = true
    this.recognition?.stop()
  }

  /** Stop listening and drop any in-flight recognition state. */
  abort(): void {
    this.stopped = true
    this.recognition?.abort()
  }

  private restart(): void {
    if (this.restarting || this.stopped || !this.recognition) return
    this.restarting = true
    try {
      this.recognition.start()
    } catch {
      // "already started" races happen on fast restart cycles — retry once.
      setTimeout(() => {
        if (!this.stopped && this.recognition) {
          try {
            this.recognition.start()
          } catch {
            /* give up — the session just won't caption this stretch */
          }
        }
      }, 250)
    } finally {
      this.restarting = false
    }
  }
}
