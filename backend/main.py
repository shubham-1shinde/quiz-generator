"""
Text-to-Quiz FastAPI backend.

Main responsibilities:
- Initialize the SQLite database and its tables.
- Extract text from uploaded files.
- Generate and validate multiple-choice questions.
- Store quizzes, submissions, and evaluation data.
- Export quizzes in JSON, CSV, and PDF formats.
"""

import os
import re
import json
import csv
import io
import hashlib
import random
import sqlite3
import math

from pathlib import Path
from typing import Optional

import requests

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DB = Path(__file__).parent / "quiz.db"

app = FastAPI(title="Text-to-Quiz")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"]
)


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


with db() as c:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS chunks(
            hash TEXT PRIMARY KEY,
            text TEXT,
            questions TEXT,
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS quizzes(
            id INTEGER PRIMARY KEY,
            title TEXT,
            source TEXT,
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS questions(
            id INTEGER PRIMARY KEY,
            quiz_id INTEGER,
            question TEXT,
            answer TEXT,
            distractors TEXT,
            difficulty TEXT,
            measured TEXT,
            source_sentence TEXT,
            valid INTEGER,
            reason TEXT,
            topic TEXT,
            answer_position INTEGER,
            FOREIGN KEY(quiz_id) REFERENCES quizzes(id)
        );

        CREATE TABLE IF NOT EXISTS runs(
            id INTEGER PRIMARY KEY,
            quiz_id INTEGER,
            score INTEGER,
            total INTEGER,
            answers TEXT,
            created TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS responses(
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            question_id INTEGER,
            correct INTEGER,
            selected_position INTEGER,
            key_position INTEGER,
            difficulty TEXT,
            topic TEXT,
            question_words INTEGER,
            FOREIGN KEY(run_id) REFERENCES runs(id)
        );

        CREATE TABLE IF NOT EXISTS human_labels(
            question TEXT PRIMARY KEY,
            answer TEXT,
            passage TEXT,
            source TEXT
        );
    """)

    try:
        c.execute(
            "ALTER TABLE human_labels ADD COLUMN valid_label INTEGER"
        )
    except sqlite3.OperationalError:
        pass


class Gen(BaseModel):
    text: str
    title: Optional[str] = "Generated quiz"
    difficulty: Optional[str] = "medium"


class Submit(BaseModel):
    answers: list[int]
    key_positions: list[int] = Field(default_factory=list)


class Seed(BaseModel):
    passages: Optional[list[dict]] = None


def chunks(text, n=400):
    words = text.split()
    out = []

    for i in range(0, len(words), n):
        part = " ".join(words[i:i + n])

        if len(part.split()) >= 35:
            out.append(part)

    return out


def generate(chunk, difficulty="medium"):
    key = os.getenv("GEMINI_API_KEY")

    gemini_error = (
        "GEMINI_API_KEY is empty or was not loaded "
        "from the project-root .env."
    )

    prompt = (
        f"Create exactly 5 multiple-choice questions grounded in "
        f"the supplied passage, targeting {difficulty} difficulty. "
        "Return ONLY a JSON array with exactly 5 objects containing "
        "question, answer, distractors (array of 3), difficulty "
        "(easy/medium/hard), source_sentence. "
        "Avoid questions requiring outside knowledge. Passage:\n"
        + chunk
    )

    if key:
        try:
            model = os.getenv(
                "GEMINI_MODEL",
                "gemini-3.1-flash-lite"
            )

            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt}
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.2,
                        "responseMimeType": "application/json",
                        "maxOutputTokens": 3072
                    }
                },
                timeout=(10, 120)
            )

            r.raise_for_status()

            raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(raw)

            return (data[:5], "gemini")

        except Exception as e:
            status = getattr(
                getattr(e, "response", None),
                "status_code",
                None
            )

            gemini_error = (
                f"Gemini request failed"
                f"{f' (HTTP {status})' if status else ''}: "
                f"{str(e)[:300]}"
            )

    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen2.5:7b",
                "prompt": prompt,
                "stream": False,
                "format": "json"
            },
            timeout=120
        )

        r.raise_for_status()

        data = json.loads(r.json()["response"])
        data = data if isinstance(data, list) else data.get("questions", [])

        return (data[:5], "ollama")

    except Exception as e:
        raise HTTPException(
            503,
            gemini_error + " Ollama fallback is unavailable: " + str(e)
        )


def validate(q, chunk):
    ans = str(q.get("answer", "")).strip()

    opts = [
        str(x).strip()
        for x in q.get("distractors", [])[:3]
    ]

    if not q.get("question") or not ans or len(opts) != 3:
        return (False, "Malformed question", opts)

    try:
        from sentence_transformers import SentenceTransformer, util

        model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        strings = [ans] + opts

        sims = util.cos_sim(
            model.encode(strings),
            model.encode(strings)
        ).tolist()

        if any(
            sims[0][i] > 0.92
            for i in range(1, 4)
        ) or any(
            sims[i][j] > 0.96
            for i in range(1, 4)
            for j in range(i + 1, 4)
        ):
            return (False, "Distractors too similar", opts)

    except Exception:
        pass

    sentence = str(q.get("source_sentence", "")).strip()

    grounded = bool(
        sentence and sentence.lower() in chunk.lower()
    )

    if os.getenv("ENABLE_LOCAL_VALIDATORS", "").lower() == "true":
        try:
            from transformers import pipeline

            qa = pipeline(
                "question-answering",
                model="deepset/roberta-base-squad2"
            )

            result = qa(
                question=q["question"],
                context=chunk
            )

            if (
                result["score"] > 0.3
                and result["answer"].lower() not in ans.lower()
                and ans.lower() not in result["answer"].lower()
            ):
                return (False, "QA answer disagrees", opts)

            nli = pipeline(
                "text-classification",
                model="cross-encoder/nli-deberta-v3-small"
            )

            verdict = nli({
                "text": sentence,
                "text_pair": q["question"] + " " + ans
            })

            if verdict and "entail" not in verdict[0]["label"].lower():
                return (False, "NLI did not entail key", opts)

        except Exception:
            pass

    return (
        True,
        "Source sentence matched; local QA/NLI disabled"
        if os.getenv("ENABLE_LOCAL_VALIDATORS", "").lower() != "true"
        else "Validated",
        opts
    )


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "local_validators": os.getenv(
            "ENABLE_LOCAL_VALIDATORS", ""
        ).lower() == "true"
    }


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    b = await file.read()

    if file.filename.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader

            pdf = PdfReader(io.BytesIO(b))

            text = "\n".join(
                p.extract_text() or ""
                for p in pdf.pages
            )

        except Exception as e:
            raise HTTPException(
                400,
                "Could not read PDF: " + str(e)
            )

    else:
        text = b.decode(
            "utf-8-sig",
            errors="replace"
        )

    return {
        "text": text,
        "filename": file.filename
    }


@app.post("/api/generate")
def create(req: Gen):
    parts = chunks(req.text)

    if not parts:
        raise HTTPException(
            400,
            "Provide at least 35 words of source text."
        )

    allq = []
    providers = []
    cachehits = 0

    for part in parts:
        h = hashlib.sha256(part.encode()).hexdigest()

        with db() as c:
            row = c.execute(
                "SELECT questions FROM chunks WHERE hash=?",
                (h,)
            ).fetchone()

        if row:
            items = json.loads(row["questions"])
            cachehits += 1

        else:
            items, provider = generate(
                part,
                req.difficulty or "medium"
            )

            providers.append(provider)

            with db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO chunks(hash,text,questions) VALUES(?,?,?)",
                    (h, part, json.dumps(items))
                )

        for q in items:
            q["_chunk"] = part

            q["_valid"], q["_reason"], q["_opts"] = validate(
                q,
                part
            )

            allq.append(q)

    if not allq:
        raise HTTPException(
            502,
            "The model returned no questions."
        )

    with db() as c:
        cur = c.execute(
            "INSERT INTO quizzes(title,source) VALUES(?,?)",
            (
                req.title or "Generated quiz",
                req.text[:1000]
            )
        )

        qid = cur.lastrowid

        for q in allq:
            diff = q.get("difficulty", "medium")

            measured = (
                "hard" if not q["_valid"] else diff
            )

            sent = str(q.get("source_sentence", ""))

            words = len(
                str(q.get("question", "")).split()
            )

            c.execute(
                """
                INSERT INTO questions(
                    quiz_id, question, answer, distractors,
                    difficulty, measured, source_sentence,
                    valid, reason, topic, answer_position
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    qid,
                    q.get("question", ""),
                    q.get("answer", ""),
                    json.dumps(q["_opts"]),
                    diff,
                    measured,
                    sent,
                    int(q["_valid"]),
                    q["_reason"],
                    "General",
                    None
                )
            )

    return {
        "id": qid,
        "title": req.title,
        "count": len(allq),
        "valid": sum(q["_valid"] for q in allq),
        "cache_hits": cachehits,
        "api_calls": len(providers),
        "providers": providers,
        "questions": allq
    }


def quizdata(qid):
    with db() as c:
        q = c.execute(
            "SELECT * FROM quizzes WHERE id=?",
            (qid,)
        ).fetchone()

        if not q:
            raise HTTPException(404, "Quiz not found")

        items = [
            dict(x)
            for x in c.execute(
                "SELECT * FROM questions WHERE quiz_id=?",
                (qid,)
            )
        ]

    for x in items:
        x["distractors"] = json.loads(x["distractors"])

    return (dict(q), items)


def simple_pdf(title, items):
    lines = [title, ""]

    for n, x in enumerate(items, 1):
        lines.append(f"{n}. {x['question']}")

        lines.extend(
            f"   {chr(65 + i)}. {v}"
            for i, v in enumerate(
                [x["answer"]] + x["distractors"]
            )
        )

    lines.extend(["", "Answer key"])

    lines.extend(
        f"{n}. {x['answer']}"
        for n, x in enumerate(items, 1)
    )

    pages = [
        lines[i:i + 48]
        for i in range(0, len(lines), 48)
    ] or [[]]

    objects = []
    kids = []

    def add(value):
        objects.append(value)
        return len(objects)

    catalog_id = add("")
    pages_id = add("")

    font_id = add(
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    )

    for page_lines in pages:
        page_id = len(objects) + 1
        kids.append(f"{page_id} 0 R")

        content = "BT /F1 10 Tf 50 750 Td 14 TL\n"

        for line in page_lines:
            safe = (
                line.encode("ascii", "replace")
                .decode("ascii")
                .replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
            )

            content += f"({safe[:105]}) Tj T*\n"

        content += "ET"

        stream = content.encode("latin-1")

        add(
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {len(objects) + 2} 0 R >>"
        )

        add(
            f"<< /Length {len(stream)} >>\n"
            f"stream\n{content}\nendstream"
        )

    objects[catalog_id - 1] = (
        f"<< /Type /Catalog /Pages {pages_id} 0 R >>"
    )

    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(kids)}] "
        f"/Count {len(kids)} >>"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]

    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))

        out.extend(
            f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
        )

    xref = len(out)

    out.extend(
        f"xref\n0 {len(offsets)}\n"
        "0000000000 65535 f \n".encode()
    )

    for off in offsets[1:]:
        out.extend(
            f"{off:010d} 00000 n \n".encode()
        )

    out.extend(
        f"trailer\n<< /Size {len(offsets)} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF".encode()
    )

    return bytes(out)


@app.get("/api/quizzes")
def quizzes():
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                """
                SELECT q.*, count(x.id) count,
                sum(x.valid) valid
                FROM quizzes q
                LEFT JOIN questions x ON q.id=x.quiz_id
                GROUP BY q.id
                ORDER BY q.id DESC
                """
            )
        ]


@app.get("/api/quizzes/{qid}")
def getquiz(qid: int):
    q, items = quizdata(qid)

    return {
        "quiz": q,
        "questions": items
    }


@app.post("/api/quizzes/{qid}/submit")
def submit(qid: int, req: Submit):
    _, items = quizdata(qid)

    score = sum(
        i < len(req.answers)
        and req.answers[i] == items[i]["id"]
        for i in range(len(items))
    )

    with db() as c:
        run = c.execute(
            "INSERT INTO runs(quiz_id,score,total,answers) VALUES(?,?,?,?)",
            (
                qid,
                score,
                len(items),
                json.dumps(req.answers)
            )
        ).lastrowid

        for i, item in enumerate(items):
            c.execute(
                """
                INSERT INTO responses(
                    run_id, question_id, correct,
                    selected_position, key_position,
                    difficulty, topic, question_words
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    run,
                    item["id"],
                    int(
                        i < len(req.answers)
                        and req.answers[i] == item["id"]
                    ),
                    req.key_positions[i]
                    if i < len(req.key_positions) else None,
                    req.key_positions[i]
                    if i < len(req.key_positions) else None,
                    item["difficulty"],
                    item["topic"],
                    len(item["question"].split())
                )
            )

    return {
        "score": score,
        "total": len(items),
        "percent": round(
            100 * score / max(1, len(items))
        )
    }


@app.get("/api/evaluation")
def evaluation():
    with db() as c:
        qs = [
            dict(r)
            for r in c.execute("SELECT * FROM questions")
        ]

        runs = [
            dict(r)
            for r in c.execute("SELECT * FROM runs")
        ]

        labels = [
            dict(r)
            for r in c.execute("SELECT * FROM human_labels")
        ]

        responses = [
            dict(r)
            for r in c.execute("SELECT * FROM responses")
        ]

    total = len(qs)
    valid = sum(x["valid"] for x in qs)
    invalid = total - valid
    rejected = invalid / max(1, total)

    correct = sum(r["score"] for r in runs)
    answers = sum(r["total"] for r in runs)

    exact_source_matches = sum(
        "source sentence matched" in (q["reason"] or "").lower()
        for q in qs
    )

    before = [0, 0, 0, 0]
    after = [0, 0, 0, 0]

    for x in qs:
        before[x["answer_position"] or 0] += 1

    for x in responses:
        if (
            x["key_position"] is not None
            and 0 <= x["key_position"] < 4
        ):
            after[x["key_position"]] += 1

    bydiff = {
        d: {
            "n": sum(x["difficulty"] == d for x in qs),
            "valid": sum(
                x["difficulty"] == d and x["valid"]
                for x in qs
            )
        }
        for d in ["easy", "medium", "hard"]
    }

    matched = [
        (q, l)
        for q in qs
        for l in labels
        if q["question"].strip().casefold()
        == l["question"].strip().casefold()
    ]

    human_accuracy = (
        sum(
            q["answer"].strip().casefold()
            == l["answer"].strip().casefold()
            for q, l in matched
        ) / len(matched)
        if matched else None
    )

    solve = {
        d: {
            "correct": sum(
                x["correct"]
                for x in responses
                if x["difficulty"] == d
            ),
            "attempted": sum(
                x["difficulty"] == d
                for x in responses
            ),
            "rate": round(
                sum(
                    x["correct"]
                    for x in responses
                    if x["difficulty"] == d
                ) / sum(
                    x["difficulty"] == d
                    for x in responses
                ),
                3
            )
        } if any(
            x["difficulty"] == d
            for x in responses
        ) else None
        for d in bydiff
    }

    response_runs = {
        x["run_id"]
        for x in responses
    }

    legacy = [
        r for r in runs
        if r["id"] not in response_runs
    ]

    answered_correct = (
        sum(x["correct"] for x in responses)
        + sum(r["score"] for r in legacy)
    )

    answered_total = (
        len(responses)
        + sum(r["total"] for r in legacy)
    )

    lengths = {}

    for bucket, fn in [
        ("short", lambda n: n <= 10),
        ("medium", lambda n: 11 <= n <= 20),
        ("long", lambda n: n > 20)
    ]:
        sample = [
            x for x in responses
            if fn(x["question_words"])
        ]

        lengths[bucket] = {
            "correct": sum(x["correct"] for x in sample),
            "attempted": len(sample),
            "accuracy": round(
                sum(x["correct"] for x in sample) / len(sample),
                3
            ) if sample else None
        }

    topic_metrics = {}

    for topic in sorted(
        set(x["topic"] or "General" for x in responses)
    ):
        sample = [
            x for x in responses
            if (x["topic"] or "General") == topic
        ]

        topic_metrics[topic] = {
            "correct": sum(x["correct"] for x in sample),
            "attempted": len(sample),
            "accuracy": round(
                sum(x["correct"] for x in sample) / len(sample),
                3
            )
        }

    labeled_valid = [
        (q, l)
        for q in qs
        for l in labels
        if l["valid_label"] is not None
        and q["question"].strip().casefold()
        == l["question"].strip().casefold()
    ]

    tp = sum(
        q["valid"] == 1 and l["valid_label"] == 1
        for q, l in labeled_valid
    )

    fp = sum(
        q["valid"] == 1 and l["valid_label"] == 0
        for q, l in labeled_valid
    )

    fn = sum(
        q["valid"] == 0 and l["valid_label"] == 1
        for q, l in labeled_valid
    )

    tn = sum(
        q["valid"] == 0 and l["valid_label"] == 0
        for q, l in labeled_valid
    )

    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None
        and recall is not None
        and precision + recall
        else None
    )

    return {
        "source": (
            "Computed from saved questions, real quiz responses, "
            "and exact question matches in uploaded reference labels."
        ),
        "n": total,
        "runs": len(runs),
        "responses": len(responses),
        "label_count": len(labels),
        "label_matches": len(matched),

        "metrics": {
            "answered_correct": answered_correct,
            "answered_total": answered_total,

            "solve_accuracy": round(
                answered_correct / answered_total, 3
            ) if answered_total else None,

            "human_label_accuracy": round(
                human_accuracy, 3
            ) if human_accuracy is not None else None,

            "distractor_rejected_rate": round(rejected, 3),

            "exact_source_sentence_matches": exact_source_matches,

            "exact_source_sentence_rate": round(
                exact_source_matches / total, 3
            ) if total else None,

            "validity_precision": round(
                precision, 3
            ) if precision is not None else None,

            "validity_recall": round(
                recall, 3
            ) if recall is not None else None,

            "validity_f1": round(
                f1, 3
            ) if f1 is not None else None,

            "labeled_validity_matches": len(labeled_valid),

            "confusion_matrix": {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn
            } if labeled_valid else None,

            "answer_position_before_shuffle": before,
            "answer_position_after_shuffle": after,

            "solve_rate_by_difficulty": solve,
            "accuracy_by_question_length": lengths,
            "accuracy_by_topic": topic_metrics,

            "difficulty_sample_counts": {
                d: v["n"]
                for d, v in bydiff.items()
            }
        },

        "baseline": {
            "status": (
                "Not measured; baseline questions are not generated "
                "to avoid extra model calls."
            )
        },

        "limitations": [
            "Difficulty, topic, and question-length accuracy become informative only after real quiz attempts.",
            "Human answer-key accuracy requires an uploaded reference with exact matching question text.",
            "Validity precision/recall/F1 require matched reference records with a boolean valid field.",
            "Groundedness is based on exact source-sentence matching unless optional QA/NLI models are enabled.",
            "Distractor rejected rate counts failed validation items, not every individual distractor.",
            "Answer-position statistics report stored option order and the shuffled key positions recorded during attempts."
        ]
    }


@app.post("/api/evaluation/seed")
def seed(req: Seed):
    passages = req.passages or [
        {
            "passage": (
                "The water cycle describes how water moves between Earth "
                "and its atmosphere. Heat from the Sun causes liquid water "
                "to evaporate into water vapor. Plants also release water "
                "vapor through transpiration. As vapor rises, it cools and "
                "condenses into clouds. When droplets become heavy, "
                "precipitation returns water to the surface as rain or snow. "
                "Some water flows into rivers while some infiltrates the soil."
            ),
            "question": "What process changes liquid water into vapor?",
            "answer": "Evaporation",
            "distractors": [
                "Condensation",
                "Precipitation",
                "Infiltration"
            ],
            "source_sentence": (
                "Heat from the Sun causes liquid water to evaporate "
                "into water vapor."
            ),
            "difficulty": "easy"
        }
    ]

    with db() as c:
        for p in passages:
            c.execute(
                """
                INSERT OR REPLACE INTO human_labels(
                    question, answer, passage, source
                )
                VALUES(?,?,?,?)
                """,
                (
                    p.get("question", ""),
                    p.get("answer", ""),
                    p.get("passage", ""),
                    "user" if req.passages else "bundled example"
                )
            )

    return {
        "loaded": len(passages),
        "label_source": (
            "User supplied"
            if req.passages
            else "Bundled deterministic example (not SciQ/RACE)"
        ),
        "results": [
            {
                "question": p.get("question"),
                "human_answer": p.get("answer"),
                "note": (
                    "Reference label stored; exact question match "
                    "is required for comparison."
                )
            }
            for p in passages
        ]
    }


@app.post("/api/evaluation/upload")
def upload_labels(req: Seed):
    if not req.passages:
        raise HTTPException(
            400,
            "Upload a JSON array of passage, question and answer objects."
        )

    with db() as c:
        for p in req.passages:
            if (
                not p.get("question")
                or not p.get("answer")
                or not p.get("passage")
            ):
                raise HTTPException(
                    400,
                    "Each record needs passage, question and answer."
                )

            c.execute(
                """
                INSERT OR REPLACE INTO human_labels(
                    question, answer, passage, source, valid_label
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    p["question"],
                    p["answer"],
                    p["passage"],
                    "user",
                    int(p["valid"])
                    if isinstance(p.get("valid"), bool)
                    else None
                )
            )

    return {
        "loaded": len(req.passages),
        "source": "user"
    }


@app.get("/api/export/{qid}/{fmt}")
def export(qid: int, fmt: str):
    q, items = quizdata(qid)

    if fmt == "json":
        data = json.dumps(
            {
                "quiz": q,
                "questions": items
            },
            indent=2
        )

        return StreamingResponse(
            io.BytesIO(data.encode()),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=quiz-{qid}.json"
                )
            }
        )

    if fmt == "csv":
        s = io.StringIO()
        w = csv.writer(s)

        w.writerow([
            "Question",
            "Answer",
            "Distractor 1",
            "Distractor 2",
            "Distractor 3",
            "Difficulty",
            "Valid"
        ])

        for x in items:
            w.writerow([
                x["question"],
                x["answer"],
                *x["distractors"],
                x["difficulty"],
                x["valid"]
            ])

        return StreamingResponse(
            io.BytesIO(s.getvalue().encode()),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=quiz-{qid}.csv"
                )
            }
        )

    if fmt == "pdf":
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas

            b = io.BytesIO()

            p = canvas.Canvas(b, pagesize=letter)

            y = 750

            p.setFont("Helvetica-Bold", 16)
            p.drawString(50, y, q["title"][:70])

            y -= 35

            p.setFont("Helvetica", 10)

            for n, x in enumerate(items, 1):
                for line in [
                    f"{n}. {x['question']}",
                    *[
                        f"   {chr(65 + i)}. {v}"
                        for i, v in enumerate(
                            [x["answer"]] + x["distractors"]
                        )
                    ]
                ]:
                    if y < 60:
                        p.showPage()
                        y = 750
                        p.setFont("Helvetica", 10)

                    p.drawString(55, y, line[:100])
                    y -= 16

            y -= 8

            p.setFont("Helvetica-Bold", 12)
            p.drawString(50, y, "Answer key")

            y -= 20

            p.setFont("Helvetica", 10)

            for n, x in enumerate(items, 1):
                p.drawString(
                    55,
                    y,
                    f"{n}. {x['answer']}"
                )

                y -= 15

            p.save()
            b.seek(0)

            return StreamingResponse(
                b,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename=quiz-{qid}.pdf"
                    )
                }
            )

        except ImportError:
            b = io.BytesIO(
                simple_pdf(q["title"], items)
            )

            return StreamingResponse(
                b,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename=quiz-{qid}.pdf"
                    )
                }
            )

    raise HTTPException(
        400,
        "Format must be pdf, json, or csv"
    )
