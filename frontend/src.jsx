import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  BookOpen,
  ClipboardList,
  ChartNoAxesColumn,
  Leaf,
  Upload,
  Download,
  Play,
  CheckCircle2,
  AlertCircle,
  LoaderCircle,
  ArrowRight
} from 'lucide-react';
import './style.css';

// Backend API URL
const API = 'http://localhost:8000/api';

function App() {
  // Application navigation and input states
  const [page, S] = useState('Generate');
  const [text, T] = useState('');
  const [title, Ti] = useState('Untitled quiz');
  const [difficulty, D] = useState('medium');

  // Loading and error states
  const [busy, B] = useState(false);
  const [err, E] = useState('');

  // Quiz generation and library states
  const [result, R] = useState(null);
  const [library, L] = useState([]);
  const [evaldata, V] = useState(null);

  // Quiz participation states
  const [active, A] = useState(null);
  const [answers, An] = useState([]);
  const [selected, Sel] = useState([]);
  const [score, Sc] = useState(null);

  // Fetch saved quizzes and evaluation data
  async function load() {
    try {
      L(await (await fetch(API + '/quizzes')).json());
      V(await (await fetch(API + '/evaluation')).json());
    } catch (e) {
      E('Backend unavailable. Start FastAPI on port 8000.');
    }
  }

  // Load initial application data when component mounts
  useEffect(() => {
    load();
  }, []);

  // Generate quiz using the provided source text
  async function generate() {
    E('');
    B(true);

    try {
      let r = await fetch(API + '/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          text,
          title,
          difficulty
        })
      });

      let j = await r.json();

      if (!r.ok) {
        throw Error(j.detail || 'Generation failed');
      }

      R(j);
      await load();
    } catch (e) {
      E(e.message);
    } finally {
      B(false);
    }
  }

  // Upload PDF or TXT file and extract its text
  async function file(f) {
    let fd = new FormData();
    fd.append('file', f);

    B(true);

    try {
      let r = await fetch(API + '/extract', {
        method: 'POST',
        body: fd
      });

      let j = await r.json();

      if (!r.ok) {
        throw Error(j.detail);
      }

      T(j.text);
    } catch (e) {
      E(e.message);
    } finally {
      B(false);
    }
  }

  // Fetch a quiz and shuffle its answer options
  async function take(id) {
    let j = await (await fetch(API + '/quizzes/' + id)).json();

    j.questions = j.questions.map(q => ({
      ...q,
      options: [
        { label: q.answer, correct: true },
        ...q.distractors.map(label => ({
          label,
          correct: false
        }))
      ].sort(() => Math.random() - 0.5)
    }));

    A(j);
    An([]);
    Sel([]);
    Sc(null);
    S('Take Quiz');
  }

  // Submit quiz answers and retrieve the evaluation score
  async function submit() {
    let j = await (
      await fetch(API + '/quizzes/' + active.quiz.id + '/submit', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          answers,
          key_positions: active.questions.map(q =>
            q.options.findIndex(o => o.correct)
          )
        })
      })
    ).json();

    Sc(j);
    await load();
  }

  // Sidebar navigation items
  const nav = [
    ['Generate', Leaf],
    ['Quiz Library', BookOpen],
    ['Evaluation', ChartNoAxesColumn]
  ];

  return (
    <div className="shell">

      {/* Sidebar navigation */}
      <aside>
        <div className="brand">
          <span className="mark">
            <Leaf size={20} />
          </span>

          <span>
            Fieldnote
            <small>QUIZ STUDIO</small>
          </span>
        </div>

        <nav>
          {nav.map(([n, I]) => (
            <button
              className={page === n ? 'active' : ''}
              onClick={() => S(n)}
              key={n}
            >
              <I size={18} />
              {n}
            </button>
          ))}

          {active && (
            <button
              className={page === 'Take Quiz' ? 'active' : ''}
              onClick={() => S('Take Quiz')}
            >
              <ClipboardList size={18} />
              Take Quiz
            </button>
          )}
        </nav>

        <div className="sidefoot">
          <span className="dot" />
          Local workspace
        </div>
      </aside>

      {/* Main application content */}
      <main>

        {/* Page header */}
        <header>
          <div>
            <span className="eyebrow">
              LEARNING TOOLS / {page.toUpperCase()}
            </span>

            <h1>
              {page === 'Take Quiz' ? 'Take Quiz' : page}
            </h1>
          </div>

          <span className="pill">
            <span className="dot" />
            API connected when backend is running
          </span>
        </header>

        {/* Display API and application errors */}
        {err && (
          <div className="error">
            <AlertCircle size={18} />
            {err}

            <button onClick={() => E('')}>×</button>
          </div>
        )}

        {/* ================= QUIZ GENERATION PAGE ================= */}
        {page === 'Generate' && (
          <div className="grid">

            {/* Source input section */}
            <section className="panel input-panel">
              <div className="panel-head">
                <div>
                  <h2>Build from a source</h2>
                  <p>Paste notes, a reading, or a chapter excerpt.</p>
                </div>

                <span className="step">01 / SOURCE</span>
              </div>

              <label>QUIZ TITLE</label>

              <input
                value={title}
                onChange={e => Ti(e.target.value)}
              />

              <label>SOURCE TEXT</label>

              <textarea
                placeholder="Paste your learning material here… (at least 35 words)"
                value={text}
                onChange={e => T(e.target.value)}
              />

              {/* Display source text word count */}
              <div className="textmeta">
                {text.trim() ? text.trim().split(/\s+/).length : 0} words
                <span>Chunks are cached to avoid repeat calls</span>
              </div>

              <div className="controls">

                {/* Upload source document */}
                <label className="upload">
                  <Upload size={16} />
                  Upload PDF or TXT

                  <input
                    type="file"
                    accept=".pdf,.txt"
                    onChange={e =>
                      e.target.files[0] && file(e.target.files[0])
                    }
                  />
                </label>

                {/* Select quiz difficulty */}
                <label className="difficulty">
                  Target difficulty

                  <select
                    value={difficulty}
                    onChange={e => D(e.target.value)}
                  >
                    <option>easy</option>
                    <option>medium</option>
                    <option>hard</option>
                  </select>
                </label>
              </div>

              {/* Generate quiz button */}
              <button
                className="primary"
                onClick={generate}
                disabled={busy || !text.trim()}
              >
                {busy ? (
                  <>
                    <LoaderCircle className="spin" />
                    Generating…
                  </>
                ) : (
                  <>
                    Generate quiz
                    <ArrowRight size={17} />
                  </>
                )}
              </button>

              <p className="fine">
                One generation call per new 400-word chunk · local fallback via Ollama
              </p>
            </section>

            {/* Quiz generation workflow information */}
            <section className="panel preview">
              <div className="panel-head">
                <div>
                  <h2>Quality, by design</h2>
                  <p>A source-grounded workflow in one pass.</p>
                </div>

                <span className="step">02 / REVIEW</span>
              </div>

              <div className="flow">
                {[
                  ['01', 'Generate', 'Five questions per source chunk'],
                  ['02', 'Screen', 'Distractor similarity & source check'],
                  ['03', 'Verify', 'Optional local QA and NLI models'],
                  ['04', 'Publish', 'Quiz mode, answer key, exports']
                ].map(x => (
                  <div className="flowrow" key={x[0]}>
                    <span>{x[0]}</span>

                    <div>
                      <b>{x[1]}</b>
                      <small>{x[2]}</small>
                    </div>

                    <CheckCircle2 size={17} />
                  </div>
                ))}
              </div>

              {/* Model configuration information */}
              <div className="note">
                <b>Free model setup</b>
                <p>
                  Gemini is used when a key is configured. If unavailable,
                  generation falls back to local Ollama. Model validation
                  is optional and runs locally.
                </p>
              </div>
            </section>

            {/* Display generated quiz results */}
            {result && (
              <section className="panel result">
                <div className="panel-head">
                  <div>
                    <h2>{result.title} is ready</h2>
                    <p>
                      {result.valid} of {result.count} passed the configured checks
                    </p>
                  </div>

                  <button
                    className="primary small"
                    onClick={() => take(result.id)}
                  >
                    <Play size={15} />
                    Play quiz
                  </button>
                </div>

                {/* Quiz generation metrics */}
                <div className="metrics">
                  <b>
                    {result.count}
                    <small>QUESTIONS</small>
                  </b>

                  <b>
                    {result.cache_hits}
                    <small>CACHE HITS</small>
                  </b>

                  <b>
                    {result.api_calls}
                    <small>NEW CALLS</small>
                  </b>
                </div>

                {/* Generated question preview */}
                {result.questions.map((q, i) => (
                  <article className="qcard" key={i}>
                    <b>{i + 1}. {q.question}</b>

                    <p>
                      Key: {q.answer} · {q.difficulty} ·
                      {q._valid ? 'Passed' : 'Review'} — {q._reason}
                    </p>
                  </article>
                ))}
              </section>
            )}
          </div>
        )}

        {/* ================= QUIZ LIBRARY PAGE ================= */}
        {page === 'Quiz Library' && (
          <section className="panel full">
            <div className="panel-head">
              <div>
                <h2>Your quizzes</h2>
                <p>
                  {library.length} saved quizzes · stored in SQLite
                </p>
              </div>
            </div>

            {/* Display empty state when no quizzes exist */}
            {!library.length ? (
              <div className="empty">
                <BookOpen size={28} />
                <b>No quizzes yet</b>

                <span>
                  Generate one from your source material to see it here.
                </span>

                <button
                  className="primary small"
                  onClick={() => S('Generate')}
                >
                  Create a quiz
                </button>
              </div>
            ) : (
              /* Display saved quizzes and export options */
              library.map(q => (
                <div className="librow" key={q.id}>
                  <div>
                    <b>{q.title}</b>

                    <small>
                      {q.count} questions · {q.valid || 0} validated · {q.created}
                    </small>
                  </div>

                  <div className="actions">
                    <button onClick={() => take(q.id)}>
                      <Play size={15} />
                      Take
                    </button>

                    {['pdf', 'json', 'csv'].map(f => (
                      <a
                        key={f}
                        href={`${API}/export/${q.id}/${f}`}
                      >
                        <Download size={14} />
                        {f.toUpperCase()}
                      </a>
                    ))}
                  </div>
                </div>
              ))
            )}
          </section>
        )}

        {/* ================= TAKE QUIZ PAGE ================= */}
        {page === 'Take Quiz' && active && (
          <section className="panel full quizpanel">
            <div className="panel-head">
              <div>
                <h2>{active.quiz.title}</h2>

                <p>
                  {active.questions.length} questions · correct options are shuffled
                </p>
              </div>
            </div>

            {/* Display questions and answer options */}
            {active.questions.map((q, i) => (
              <article className="playq" key={q.id}>
                <b>{i + 1}. {q.question}</b>

                {q.options.map((o, k) => (
                  <label className="option" key={k}>
                    <input
                      type="radio"
                      name={'q' + i}
                      checked={selected[i] === k}
                      onChange={() => {
                        let s = [...selected];
                        let a = [...answers];

                        s[i] = k;
                        a[i] = o.correct ? q.id : -1;

                        Sel(s);
                        An(a);
                      }}
                    />

                    {o.label}
                  </label>
                ))}

                {/* Show correct answer after submission */}
                {score && (
                  <p className="feedback">
                    Answer: {q.answer}
                  </p>
                )}
              </article>
            ))}

            {/* Submit quiz or display final score */}
            {score ? (
              <div className="score">
                Score: {score.score} / {score.total} ({score.percent}%)
              </div>
            ) : (
              <button className="primary" onClick={submit}>
                Submit answers
                <ArrowRight size={17} />
              </button>
            )}
          </section>
        )}

        {/* Display message when no quiz is selected */}
        {page === 'Take Quiz' && !active && (
          <section className="panel full empty">
            <ClipboardList />
            <b>Choose a quiz from your library</b>

            <button
              className="primary small"
              onClick={() => S('Quiz Library')}
            >
              Open library
            </button>
          </section>
        )}

        {/* ================= EVALUATION DASHBOARD ================= */}
        {page === 'Evaluation' && evaldata && (
          <>
            <section className="panel full">

              {/* Evaluation dashboard header */}
              <div className="panel-head">
                <div>
                  <h2>Observed performance</h2>

                  <p>
                    {evaldata.source} Learner solve accuracy measures quiz takers,
                    not generated-answer accuracy.
                  </p>
                </div>

                {/* Load sample labelled evaluation data */}
                <button
                  className="upload"
                  onClick={async () => {
                    let r = await fetch(API + '/evaluation/seed', {
                      method: 'POST',
                      headers: {
                        'Content-Type': 'application/json'
                      },
                      body: '{}'
                    });

                    let j = await r.json();

                    alert(
                      `Loaded ${j.loaded} labelled example. ${j.label_source}`
                    );
                  }}
                >
                  Load labelled example
                </button>
              </div>

              {/* Display evaluation metrics */}
              <div className="evalgrid">
                {[
                  ['Generated questions', evaldata.n],
                  ['Quiz attempts', evaldata.runs],
                  [
                    'Correct answers',
                    `${evaldata.metrics.answered_correct} / ${evaldata.metrics.answered_total}`
                  ],
                  [
                    'Solve accuracy',
                    evaldata.metrics.solve_accuracy == null
                      ? 'No attempts'
                      : `${(evaldata.metrics.solve_accuracy * 100).toFixed(1)}%`
                  ],
                  [
                    'Verifier / human agreement',
                    evaldata.metrics.answer_key_verifier_agreement == null
                      ? 'Not measured'
                      : `${(evaldata.metrics.answer_key_verifier_agreement * 100).toFixed(1)}%`
                  ],
                  [
                    'Questions flagged by checks',
                    evaldata.n
                      ? `${(evaldata.metrics.distractor_rejected_rate * 100).toFixed(1)}%`
                      : 'Not measured'
                  ],
                  [
                    'Exact source sentence found',
                    evaldata.metrics.exact_source_sentence_rate == null
                      ? 'Not measured'
                      : `${(evaldata.metrics.exact_source_sentence_rate * 100).toFixed(1)}%`
                  ],
                  [
                    'Human label accuracy',
                    evaldata.metrics.human_label_accuracy ?? 'Not measured'
                  ]
                ].map(x => (
                  <div className="stat" key={x[0]}>
                    <small>{x[0]}</small>
                    <b>{x[1]}</b>
                  </div>
                ))}
              </div>

              {/* Validity confusion matrix */}
              <h3>Validity confusion matrix (requires reference labels)</h3>

              <div className="matrix">
                <span>
                  True positives
                  <b>{evaldata.metrics.confusion_matrix?.tp ?? 'Not measured'}</b>
                </span>

                <span>
                  False positives
                  <b>{evaldata.metrics.confusion_matrix?.fp ?? 'Not measured'}</b>
                </span>

                <span>
                  False negatives
                  <b>{evaldata.metrics.confusion_matrix?.fn ?? 'Not measured'}</b>
                </span>

                <span>
                  True negatives
                  <b>{evaldata.metrics.confusion_matrix?.tn ?? 'Not measured'}</b>
                </span>
              </div>

              {/* Bias and answer-position calibration */}
              <h3>Bias and calibration</h3>

              <div className="matrix">
                <span>
                  Answer position before shuffle
                  <b>
                    {evaldata.metrics.answer_position_before_shuffle.join(' / ')}
                  </b>
                </span>

                <span>
                  After shuffle
                  <b>Randomized at play time</b>
                </span>

                <span>
                  Difficulty samples
                  <b>
                    {Object.entries(evaldata.metrics.difficulty_sample_counts)
                      .map(x => x.join(': '))
                      .join(' · ')}
                  </b>
                </span>

                <span>
                  Human baseline
                  <b>Not measured</b>
                </span>
              </div>

              {/* Accuracy grouped by question length */}
              <h3>Accuracy by question length</h3>

              <div className="matrix">
                {Object.entries(evaldata.metrics.accuracy_by_question_length)
                  .map(([k, v]) => (
                    <span key={k}>
                      {k}

                      <b>
                        {v.attempted
                          ? `${v.correct}/${v.attempted} (${(v.accuracy * 100).toFixed(0)}%)`
                          : 'no attempts'}
                      </b>
                    </span>
                  ))}
              </div>

              {/* Display evaluation limitations */}
              <h3>Limitations from this run</h3>

              {evaldata.limitations.map((x, i) => (
                <p className="limitation" key={i}>
                  · {x}
                </p>
              ))}

              {/* Upload labelled JSON evaluation dataset */}
              <button
                className="upload"
                onClick={() =>
                  document.getElementById('evalupload').click()
                }
              >
                Upload labelled JSON

                <input
                  id="evalupload"
                  hidden
                  type="file"
                  accept="application/json"
                  onChange={async e => {
                    if (e.target.files[0]) {
                      try {
                        let data = JSON.parse(
                          await e.target.files[0].text()
                        );

                        let r = await fetch(API + '/evaluation/upload', {
                          method: 'POST',
                          headers: {
                            'Content-Type': 'application/json'
                          },
                          body: JSON.stringify({
                            passages: data
                          })
                        });

                        let j = await r.json();

                        if (!r.ok) {
                          throw Error(j.detail);
                        }

                        alert(`Loaded ${j.loaded} labelled examples`);
                        await load();
                      } catch (err) {
                        alert(err.message);
                      }
                    }
                  }}
                />
              </button>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

// Render the React application
createRoot(document.getElementById('root')).render(<App />);
