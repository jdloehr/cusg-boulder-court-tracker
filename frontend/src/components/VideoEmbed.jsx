// Phase 9 doc: "embed it appropriately" for a pasted video URL (YouTube,
// Vimeo, or a direct file link) or a directly-uploaded file -- an iframe
// embed for YouTube/Vimeo, a native <video> tag for anything else
// (a direct file link, or an uploaded file served from our own API).
const YOUTUBE_RE = /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([\w-]{6,})/;
const VIMEO_RE = /vimeo\.com\/(\d+)/;

export default function VideoEmbed({ videoUrl, uploadedVideoUrl }) {
  if (uploadedVideoUrl) {
    return (
      <div className="video-embed">
        <video controls src={uploadedVideoUrl} />
      </div>
    );
  }
  if (!videoUrl) return null;

  const youtubeMatch = videoUrl.match(YOUTUBE_RE);
  if (youtubeMatch) {
    return (
      <div className="video-embed">
        <iframe
          src={`https://www.youtube.com/embed/${youtubeMatch[1]}`}
          title="YouTube video"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      </div>
    );
  }

  const vimeoMatch = videoUrl.match(VIMEO_RE);
  if (vimeoMatch) {
    return (
      <div className="video-embed">
        <iframe
          src={`https://player.vimeo.com/video/${vimeoMatch[1]}`}
          title="Vimeo video"
          allow="autoplay; fullscreen; picture-in-picture"
          allowFullScreen
        />
      </div>
    );
  }

  // Not a recognized YouTube/Vimeo link -- treat as a direct video file URL.
  return (
    <div className="video-embed">
      <video controls src={videoUrl} />
    </div>
  );
}
