import os
import glob
import logging
from dotenv import load_dotenv

load_dotenv(override=True)

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("indexer")


def index_docs():
    """
    Reads PDFs from backend/data, chunks them, and stores vectors
    in a local ChromaDB collection (no Azure required).
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.join(current_dir, "../../backend/data")
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./backend/data/chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION_NAME", "brand-compliance-rules")

    logger.info("=" * 60)
    logger.info("Environment Configuration Check:")
    logger.info(f"OPENAI_API_KEY set: {bool(os.getenv('OPENAI_API_KEY'))}")
    logger.info(f"Embedding Model: text-embedding-3-small (OpenAI)")
    logger.info(f"ChromaDB persist dir: {persist_dir}")
    logger.info(f"Collection: {collection_name}")
    logger.info("=" * 60)

    required_vars = ["OPENAI_API_KEY"]
    missing_vars = [v for v in required_vars if not os.getenv(v)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        return

    # Initialize embedding model
    try:
        logger.info("Initializing OpenAI Embeddings (text-embedding-3-small)...")
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        logger.info("Embeddings model initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize embeddings: {e}")
        return

    # Initialize ChromaDB vector store
    try:
        logger.info("Initializing ChromaDB vector store...")
        vector_store = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=persist_dir
        )
        logger.info(f"ChromaDB ready at: {persist_dir}")
    except Exception as e:
        logger.error(f"Failed to initialize ChromaDB: {e}")
        return

    # Find PDF files
    pdf_files = glob.glob(os.path.join(data_folder, "*.pdf"))
    if not pdf_files:
        logger.warning(f"No PDFs found in {data_folder}. Please add compliance rule documents.")
        return

    logger.info(f"Found {len(pdf_files)} PDFs: {[os.path.basename(f) for f in pdf_files]}")

    all_splits = []

    for pdf_path in pdf_files:
        try:
            logger.info(f"Loading: {os.path.basename(pdf_path)}...")
            loader = PyPDFLoader(pdf_path)
            raw_docs = loader.load()

            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200
            )
            splits = text_splitter.split_documents(raw_docs)

            for split in splits:
                split.metadata["source"] = os.path.basename(pdf_path)

            all_splits.extend(splits)
            logger.info(f" -> Split into {len(splits)} chunks.")
        except Exception as e:
            logger.error(f"Failed to process {pdf_path}: {e}")

    if all_splits:
        logger.info(f"Uploading {len(all_splits)} chunks to ChromaDB...")
        try:
            vector_store.add_documents(documents=all_splits)
            logger.info("=" * 60)
            logger.info("Indexing Complete! The Knowledge Base is ready.")
            logger.info(f"Total chunks indexed: {len(all_splits)}")
            logger.info("=" * 60)
        except Exception as e:
            logger.error(f"Failed to add documents to ChromaDB: {e}")
    else:
        logger.warning("No documents were processed.")


if __name__ == "__main__":
    index_docs()
