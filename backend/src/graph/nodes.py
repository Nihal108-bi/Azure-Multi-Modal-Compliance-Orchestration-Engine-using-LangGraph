import json
import os
import logging
import re
from typing import Dict, Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.messages import SystemMessage, HumanMessage

from backend.src.graph.state import VideoAuditState
from backend.src.services.video_indexer import VideoIndexerService

logger = logging.getLogger("brand-guardian")
logging.basicConfig(level=logging.INFO)


# --- NODE 1: THE INDEXER ---
def index_video_node(state: VideoAuditState) -> Dict[str, Any]:
    """
    Extracts transcript from a YouTube video.
    Tries free subtitle extraction first; falls back to OpenAI Whisper API.
    """
    video_url = state.get("video_url")
    logger.info(f"--- [Node: Indexer] Processing: {video_url} ---")

    try:
        vi_service = VideoIndexerService()
        result = vi_service.process_video(video_url)
        logger.info("--- [Node: Indexer] Extraction Complete ---")
        return result
    except Exception as e:
        logger.error(f"Video Processing Failed: {e}")
        return {
            "errors": [str(e)],
            "final_status": "FAIL",
            "transcript": "",
            "ocr_text": []
        }


# --- NODE 2: THE COMPLIANCE AUDITOR ---
def audit_content_node(state: VideoAuditState) -> Dict[str, Any]:
    """
    Performs Retrieval-Augmented Generation (RAG) to audit the video content
    against brand compliance rules stored in the local ChromaDB vector store.
    """
    logger.info("--- [Node: Auditor] Querying Knowledge Base & LLM ---")

    transcript = state.get("transcript", "")
    if not transcript:
        logger.warning("No transcript available. Skipping audit.")
        return {
            "final_status": "FAIL",
            "final_report": "Audit skipped because video processing failed (No Transcript)."
        }

    llm = ChatOpenAI(
        model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.0
    )

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=os.getenv("OPENAI_API_KEY"),
    )

    vector_store = Chroma(
        collection_name=os.getenv("CHROMA_COLLECTION_NAME", "brand-compliance-rules"),
        embedding_function=embeddings,
        persist_directory=os.getenv("CHROMA_PERSIST_DIR", "./backend/data/chroma_db")
    )

    # RAG Retrieval
    ocr_text = state.get("ocr_text", [])
    query_text = f"{transcript} {' '.join(ocr_text)}"
    docs = vector_store.similarity_search(query_text, k=3)
    retrieved_rules = "\n\n".join([doc.page_content for doc in docs])

    system_prompt = f"""
    You are a Senior Brand Compliance Auditor.

    OFFICIAL REGULATORY RULES:
    {retrieved_rules}

    INSTRUCTIONS:
    1. Analyze the Transcript and OCR text below.
    2. Identify ANY violations of the rules.
    3. Return strictly JSON in the following format:

    {{
        "compliance_results": [
            {{
                "category": "Claim Validation",
                "severity": "CRITICAL",
                "description": "Explanation of the violation..."
            }}
        ],
        "status": "FAIL",
        "final_report": "Summary of findings..."
    }}

    If no violations are found, set "status" to "PASS" and "compliance_results" to [].
    """

    user_message = f"""
    VIDEO METADATA: {state.get('video_metadata', {})}
    TRANSCRIPT: {transcript}
    ON-SCREEN TEXT (OCR): {ocr_text}
    """

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ])

        content = response.content
        if "```" in content:
            content = re.search(r"```(?:json)?(.*?)```", content, re.DOTALL).group(1)

        audit_data = json.loads(content.strip())

        return {
            "compliance_results": audit_data.get("compliance_results", []),
            "final_status": audit_data.get("status", "FAIL"),
            "final_report": audit_data.get("final_report", "No report generated.")
        }

    except Exception as e:
        logger.error(f"System Error in Auditor Node: {str(e)}")
        logger.error(f"Raw LLM Response: {response.content if 'response' in locals() else 'None'}")
        return {
            "errors": [str(e)],
            "final_status": "FAIL"
        }
