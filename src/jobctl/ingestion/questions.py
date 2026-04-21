"""Durable refinement question storage."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from jobctl.ingestion.schemas import RefinementQuestion
from jobctl.llm.schemas import ExtractedFact


class RefinementQuestionStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_question(self, question: RefinementQuestion) -> str:
        existing = self.find_equivalent(question)
        if existing is not None:
            return str(existing.id)
        question_id = question.id or uuid.uuid4().hex
        now = _utc_now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO refinement_questions (
                    id, source_type, source_ref, target_node_id, fact_json, category,
                    prompt, options_json, allow_free_text, status, answer_text,
                    answer_json, priority, created_at, answered_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question_id,
                    question.source_type,
                    question.source_ref,
                    question.target_node_id,
                    _fact_json(question.fact),
                    question.category,
                    question.prompt,
                    json.dumps(question.options),
                    1 if question.allow_free_text else 0,
                    question.status,
                    question.answer_text,
                    json.dumps(question.answer_json) if question.answer_json is not None else None,
                    question.priority,
                    question.created_at or now,
                    question.answered_at,
                ),
            )
        return question_id

    def create_many(self, questions: list[RefinementQuestion]) -> list[str]:
        return [self.create_question(question) for question in questions]

    def find_equivalent(self, question: RefinementQuestion) -> RefinementQuestion | None:
        prompt_key = _prompt_key(question.prompt)
        rows = self._conn.execute(
            """
            SELECT *
            FROM refinement_questions
            WHERE source_type = ?
              AND COALESCE(source_ref, '') = COALESCE(?, '')
              AND COALESCE(target_node_id, '') = COALESCE(?, '')
              AND category = ?
              AND status IN ('pending', 'answered', 'converted_to_update')
            """,
            (
                question.source_type,
                question.source_ref,
                question.target_node_id,
                question.category,
            ),
        ).fetchall()
        for row in rows:
            candidate = _row_to_question(row)
            if _prompt_key(candidate.prompt) == prompt_key:
                return candidate
        return None

    def list_pending(
        self,
        *,
        source_ref: str | None = None,
        target_node_id: str | None = None,
        limit: int | None = None,
    ) -> list[RefinementQuestion]:
        clauses = ["status = 'pending'"]
        values: list[Any] = []
        if source_ref is not None:
            clauses.append("source_ref = ?")
            values.append(source_ref)
        if target_node_id is not None:
            clauses.append("target_node_id = ?")
            values.append(target_node_id)
        limit_clause = " LIMIT ?" if limit is not None else ""
        if limit is not None:
            values.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT *
            FROM refinement_questions
            WHERE {" AND ".join(clauses)}
            ORDER BY priority DESC, created_at ASC
            {limit_clause}
            """,
            values,
        ).fetchall()
        return [_row_to_question(row) for row in rows]

    def get(self, question_id: str) -> RefinementQuestion | None:
        row = self._conn.execute(
            "SELECT * FROM refinement_questions WHERE id = ?",
            (question_id,),
        ).fetchone()
        return _row_to_question(row) if row else None

    def mark_answered(
        self,
        question_id: str,
        answer_text: str,
        answer_json: dict[str, Any] | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                UPDATE refinement_questions
                SET status = 'answered', answer_text = ?, answer_json = ?, answered_at = ?
                WHERE id = ?
                """,
                (
                    answer_text,
                    json.dumps(answer_json) if answer_json is not None else None,
                    _utc_now(),
                    question_id,
                ),
            )

    def mark_skipped(self, question_id: str) -> None:
        self._set_status(question_id, "skipped")

    def dismiss(self, question_id: str) -> None:
        self._set_status(question_id, "dismissed")

    def mark_converted_to_update(self, question_id: str) -> None:
        self._set_status(question_id, "converted_to_update")

    def _set_status(self, question_id: str, status: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE refinement_questions SET status = ? WHERE id = ?",
                (status, question_id),
            )


def _row_to_question(row: sqlite3.Row) -> RefinementQuestion:
    fact_payload = json.loads(row["fact_json"]) if row["fact_json"] else None
    answer_payload = json.loads(row["answer_json"]) if row["answer_json"] else None
    return RefinementQuestion(
        id=row["id"],
        source_type=row["source_type"],
        source_ref=row["source_ref"] or "",
        target_node_id=row["target_node_id"],
        fact=ExtractedFact.model_validate(fact_payload) if fact_payload else None,
        category=row["category"],
        prompt=row["prompt"],
        options=json.loads(row["options_json"] or "[]"),
        allow_free_text=bool(row["allow_free_text"]),
        status=row["status"],
        answer_text=row["answer_text"],
        answer_json=answer_payload,
        priority=int(row["priority"]),
        created_at=row["created_at"],
        answered_at=row["answered_at"],
    )


def _fact_json(fact: ExtractedFact | None) -> str | None:
    return fact.model_dump_json() if fact is not None else None


def _prompt_key(prompt: str) -> str:
    return " ".join(prompt.casefold().split())


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["RefinementQuestionStore"]
