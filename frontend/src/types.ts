export type OcrFrame = {
  t: number;
  text: string;
};

export type ScreenTextResult = {
  interval_sec: number;
  frames: OcrFrame[];
  lines_deduped: string[];
  method: string;
};

export type TranscriptionResult = {
  video_id: string;
  original_filename: string;
  text: string;
  segments: { start: number; end: number; text: string }[];
  language: string | null;
  duration: number | null;
  screen_text: ScreenTextResult | null;
};

export type ExtractedFacts = {
  summary: string;
  topics: string[];
  entities: string[];
  sentiment: string | null;
  calls_to_action: string[];
  handles: string[];
  urls: string[];
  method: string;
};

export type TranscriptWithExtraction = TranscriptionResult & {
  extraction?: ExtractedFacts;
};

export type LibraryListItem = {
  video_id: string;
  original_filename: string;
  created_at: string;
  language: string | null;
  duration: number | null;
  has_extraction: boolean;
  preview?: string | null;
};

export type LibraryDetail = TranscriptionResult & {
  created_at: string;
  extraction: ExtractedFacts | null;
};

export type HealthInfo = {
  url_import_enabled?: boolean;
  yt_dlp?: boolean;
  url_import_hosts?: string;
};
