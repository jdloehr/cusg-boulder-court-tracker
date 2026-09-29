import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import VideoEmbed from "../components/VideoEmbed.jsx";
import { CASE_CATEGORY_LABELS } from "../courtInfo.js";

const HEARING_TYPE_LABELS = {
  jury_trial: "Jury Trial",
  oral_argument_motions: "Oral Argument / Motions Hearing",
};

// Page-redesign doc, Page 4: the Learn grid's card shows a short excerpt
// with a "Read the full guide" link -- this is where that link goes,
// showing the topic's full body_text/video/links (what the pre-redesign
// Learn.jsx used to render inline on the grid itself).
export default function LearnTopicDetail() {
  const { id } = useParams();
  const [topic, setTopic] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getLearnTopic(id).then(setTopic).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p className="message-error">Couldn't load this topic: {error}</p>;
  if (!topic) return <p>Loading&hellip;</p>;

  return (
    <article>
      <p>
        <Link to="/learn">&larr; Back to Learn</Link>
      </p>
      <h1>{topic.title}</h1>
      <p>
        {topic.applies_to_hearing_type_category && (
          <span className="badge badge-category">{HEARING_TYPE_LABELS[topic.applies_to_hearing_type_category]}</span>
        )}{" "}
        {topic.applies_to_case_category && (
          <span className="badge badge-category">{CASE_CATEGORY_LABELS[topic.applies_to_case_category]}</span>
        )}
      </p>
      <p className="blurb" style={{ whiteSpace: "pre-wrap" }}>{topic.body_text}</p>
      <VideoEmbed videoUrl={topic.video_url} uploadedVideoUrl={topic.has_uploaded_video ? api.learnTopicVideoUrl(topic.id) : null} />
      {topic.external_links.length > 0 && (
        <>
          <h3>Further reading</h3>
          <ul>
            {topic.external_links.map((link, i) => (
              <li key={i}>
                <a href={link.url} target="_blank" rel="noreferrer">{link.label}</a>
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}
