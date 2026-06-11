import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";

export interface VisionPrediction {
  lipClosureScore: number; // 0=fully open, 1=fully closed
  gazeStability: number;  // 0=looking away/unstable, 1=steady forward
  headStillness: number;  // 0=moving, 1=still
}

const SUPPRESSED_VISION_PATTERNS = [
  "Created TensorFlow Lite XNNPACK delegate for CPU",
  "Feedback manager requires a model with a single signature inference",
  "Sets FaceBlendshapesGraph acceleration to xnnpack by default",
  "OpenGL error checking is disabled",
  "TfLiteRuntime",
  "XNNPACK",
  "vulkan",
  "metal",
  "coreml",
  "DirectX",
];

declare global {
  interface Window {
    __antigravityVisionConsoleFilterInstalled?: boolean;
  }
}

function shouldSuppressVisionLog(args: unknown[]) {
  return args.some((arg) => {
    const text = typeof arg === "string" ? arg : String(arg ?? "");
    return SUPPRESSED_VISION_PATTERNS.some((pattern) => text.includes(pattern));
  });
}

function installVisionConsoleFilter() {
  if (typeof window === "undefined" || window.__antigravityVisionConsoleFilterInstalled) return;
  window.__antigravityVisionConsoleFilterInstalled = true;
  const originalError = console.error.bind(console);
  const originalWarn = console.warn.bind(console);

  console.error = (...args: unknown[]) => {
    if (shouldSuppressVisionLog(args)) return;
    originalError(...args);
  };

  console.warn = (...args: unknown[]) => {
    if (shouldSuppressVisionLog(args)) return;
    originalWarn(...args);
  };
}

export class CVSensor {
  private faceLandmarker: FaceLandmarker | null = null;
  private initState: "idle" | "loading" | "ready" | "failed" = "idle";
  private lastTimestampMs = 0;

  constructor() {
    installVisionConsoleFilter();
  }

  private withSuppressedVisionLogs<T>(fn: () => T): T {
    const originalError = console.error;
    const originalWarn = console.warn;

    console.error = (...args: unknown[]) => {
      if (shouldSuppressVisionLog(args)) return;
      originalError(...args);
    };

    console.warn = (...args: unknown[]) => {
      if (shouldSuppressVisionLog(args)) return;
      originalWarn(...args);
    };

    try {
      return fn();
    } finally {
      console.error = originalError;
      console.warn = originalWarn;
    }
  }

  private async initialize() {
    if (this.initState !== "idle") return;
    this.initState = "loading";
    try {
      const filesetResolver = await FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm"
      );
      this.faceLandmarker = await FaceLandmarker.createFromOptions(filesetResolver, {
        baseOptions: {
          modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
          // CPU delegate avoids the GPU→XNNPACK fallback that spams console.error
          delegate: "CPU",
        },
        outputFaceBlendshapes: true,
        runningMode: "VIDEO",
        numFaces: 1,
      });
      this.initState = "ready";
      console.log("[Vision] MediaPipe FaceLandmarker initialized.");
    } catch (err) {
      this.initState = "failed"; // don't retry — avoids infinite loop if model load fails
      console.error("[Vision] Failed to initialize MediaPipe:", err);
    }
  }

  public async getPrediction(video: HTMLVideoElement): Promise<VisionPrediction | null> {
    if (this.initState === "failed") return null;
    if (this.initState === "loading") return null;
    if (!this.faceLandmarker) {
      await this.initialize();
      return null;
    }

    if (video.readyState < 2) return null;

    // Rate-limit to ~30fps — MediaPipe crashes if called with identical or very close timestamps
    const now = performance.now();
    if (now - this.lastTimestampMs < 33) return null;
    this.lastTimestampMs = now;

    let result;
    try {
      result = this.withSuppressedVisionLogs(() =>
        this.faceLandmarker!.detectForVideo(video, now)
      );
    } catch {
      return null;
    }
    if (!result || !result.faceLandmarks || result.faceLandmarks.length === 0) {
      return null;
    }

    const landmarks = result.faceLandmarks[0];

    // 1. Lip Closure
    // Landmark 13: Upper inner lip center
    // Landmark 14: Lower inner lip center
    // Normalization: use distance between mid-nose (1) and chin (152) or inner eye distance.
    const upperLip = landmarks[13];
    const lowerLip = landmarks[14];
    const lipDist = Math.sqrt(
      Math.pow(upperLip.x - lowerLip.x, 2) + Math.pow(upperLip.y - lowerLip.y, 2) + Math.pow(upperLip.z - lowerLip.z, 2)
    );

    // Heuristic threshold: ~0.015 is usually open, < 0.005 is closed. 
    // Normalized to 0 (open) -> 1 (closed)
    const lipClosure = Math.max(0, Math.min(1, 1 - (lipDist / 0.02)));

    // 2. Gaze/Head Stability
    // We use the blendshapes if available for "EyeLookIn/Out" or just landmark stability.
    // Here we use the FaceBlendshapes 'mouthSmile' or 'jawOpen' as additional signals.
    const blendshapes = result.faceBlendshapes?.[0]?.categories || [];
    const jawOpen = blendshapes.find(c => c.categoryName === "jawOpen")?.score ?? 0;
    
    // Joint score: if jaw is open, lip closure is low.
    const adjustedLipClosure = Math.min(lipClosure, 1 - jawOpen);

    // 3. Head Stillness (Eye/Gaze hint)
    // We can check eyeLookInLeft/Right etc.
    const eyeLookInLeft = blendshapes.find(c => c.categoryName === "eyeLookInLeft")?.score ?? 0;
    const eyeLookInRight = blendshapes.find(c => c.categoryName === "eyeLookInRight")?.score ?? 0;
    const eyeLookOutLeft = blendshapes.find(c => c.categoryName === "eyeLookOutLeft")?.score ?? 0;
    const eyeLookOutRight = blendshapes.find(c => c.categoryName === "eyeLookOutRight")?.score ?? 0;
    
    // If eyes are looking far left/right, gaze stability is lower.
    const gazeStability = 1 - Math.max(eyeLookInLeft, eyeLookInRight, eyeLookOutLeft, eyeLookOutRight);

    return {
      lipClosureScore: adjustedLipClosure,
      gazeStability: gazeStability,
      headStillness: 1, // Optional: track head pos over time for this.
    };
  }
}
