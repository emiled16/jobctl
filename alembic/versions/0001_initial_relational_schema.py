"""Initial relational schema.

Revision ID: 0001
Revises:
Create Date: 2026-04-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "_migrations",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("applied_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "nodes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("properties", sa.Text()),
        sa.Column("text_representation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_nodes_type", "nodes", ["type"])
    op.create_table(
        "edges",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source_id", sa.Text(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.Text(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("properties", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_edges_source_id", "edges", ["source_id"])
    op.create_index("idx_edges_target_id", "edges", ["target_id"])
    op.create_index("idx_edges_relation", "edges", ["relation"])
    op.create_table(
        "applications",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="evaluated"),
        sa.Column("fit_score", sa.REAL()),
        sa.Column("location", sa.Text()),
        sa.Column("compensation", sa.Text()),
        sa.Column("jd_raw", sa.Text()),
        sa.Column("jd_structured", sa.Text()),
        sa.Column("evaluation_structured", sa.Text()),
        sa.Column("resume_yaml_path", sa.Text()),
        sa.Column("cover_letter_yaml_path", sa.Text()),
        sa.Column("resume_pdf_path", sa.Text()),
        sa.Column("cover_letter_pdf_path", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("recruiter_name", sa.Text()),
        sa.Column("recruiter_email", sa.Text()),
        sa.Column("recruiter_linkedin", sa.Text()),
        sa.Column("follow_up_date", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_applications_status", "applications", ["status"])
    op.create_index("idx_applications_company", "applications", ["company"])
    op.create_table(
        "application_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("application_id", sa.Text(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_application_events_application_id", "application_events", ["application_id"])
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("cursor", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text()),
    )
    op.create_index("idx_ingestion_jobs_source", "ingestion_jobs", ["source_type", "source_key"])
    op.create_index("idx_ingestion_jobs_state", "ingestion_jobs", ["state"])
    op.create_table(
        "ingested_items",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("job_id", sa.Text(), sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("external_updated_at", sa.Text()),
        sa.Column("node_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="done"),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_ingested_items_job", "ingested_items", ["job_id"])
    op.create_index("idx_ingested_items_external", "ingested_items", ["job_id", "external_id"], unique=True)
    op.create_table(
        "node_sources",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("node_id", sa.Text(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text()),
        sa.Column("confidence", sa.REAL()),
        sa.Column("source_quote", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_node_sources_node", "node_sources", ["node_id"])
    op.create_index("idx_node_sources_type", "node_sources", ["source_type"])
    op.create_table("agent_sessions", sa.Column("id", sa.Text(), primary_key=True), sa.Column("created_at", sa.Text(), nullable=False), sa.Column("updated_at", sa.Text(), nullable=False), sa.Column("state_json", sa.Text(), nullable=False))
    op.create_table("curation_proposals", sa.Column("id", sa.Text(), primary_key=True), sa.Column("kind", sa.Text(), nullable=False), sa.Column("payload_json", sa.Text(), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="pending"), sa.Column("created_at", sa.Text(), nullable=False), sa.Column("decided_at", sa.Text()))
    op.create_index("idx_curation_proposals_status", "curation_proposals", ["status"])
    op.create_index("idx_curation_proposals_kind", "curation_proposals", ["kind"])
    op.create_table("embedding_meta", sa.Column("node_id", sa.Text(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True), sa.Column("embedding_model", sa.Text(), nullable=False), sa.Column("updated_at", sa.Text(), nullable=False))
    op.create_table("refinement_questions", sa.Column("id", sa.Text(), primary_key=True), sa.Column("source_type", sa.Text(), nullable=False), sa.Column("source_ref", sa.Text()), sa.Column("target_node_id", sa.Text(), sa.ForeignKey("nodes.id", ondelete="SET NULL")), sa.Column("fact_json", sa.Text()), sa.Column("category", sa.Text(), nullable=False), sa.Column("prompt", sa.Text(), nullable=False), sa.Column("options_json", sa.Text(), nullable=False), sa.Column("allow_free_text", sa.Integer(), nullable=False, server_default="1"), sa.Column("status", sa.Text(), nullable=False, server_default="pending"), sa.Column("answer_text", sa.Text()), sa.Column("answer_json", sa.Text()), sa.Column("priority", sa.Integer(), nullable=False, server_default="0"), sa.Column("created_at", sa.Text(), nullable=False), sa.Column("answered_at", sa.Text()))
    op.create_index("idx_refinement_questions_status", "refinement_questions", ["status"])
    op.create_index("idx_refinement_questions_target", "refinement_questions", ["target_node_id"])
    op.create_index("idx_refinement_questions_source", "refinement_questions", ["source_type", "source_ref"])


def downgrade() -> None:
    for table in [
        "refinement_questions",
        "embedding_meta",
        "curation_proposals",
        "agent_sessions",
        "node_sources",
        "ingested_items",
        "ingestion_jobs",
        "application_events",
        "applications",
        "edges",
        "nodes",
        "_migrations",
    ]:
        op.drop_table(table)
