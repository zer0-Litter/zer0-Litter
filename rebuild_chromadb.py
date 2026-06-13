import os
import logging
from pymongo import MongoClient
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from chromadb import HttpClient
from config import settings
from chatbot.chatbot_core import preprocess_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['complaints_db']
complaints_collection = db['complaints']

CHROMA_DB_HOST = os.getenv("CHROMA_DB_HOST")
CHROMA_DB_PORT = os.getenv("CHROMA_DB_PORT", 8000)

embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)

try:
    chroma_client = HttpClient(host=CHROMA_DB_HOST, port=CHROMA_DB_PORT)
    try:
        chroma_client.delete_collection(name="complaint_embeddings")
        logger.info("기존 'complaint_embeddings' 컬렉션을 성공적으로 삭제했습니다.")
    except Exception as e:
        logger.warning("컬렉션 삭제 중 오류 발생: %s. 컬렉션이 존재하지 않을 수 있습니다.", e)

    vector_store = Chroma(
        collection_name="complaint_embeddings",
        embedding_function=embeddings,
        client=chroma_client
    )

    logger.info("MongoDB에서 민원 데이터를 불러오는 중...")
    complaints_data = list(complaints_collection.find({}))

    texts_to_embed = []
    metadatas_to_add = []  # 메타데이터 리스트 추가

    for doc in complaints_data:
        # 'com_contents' 필드에서 민원 내용 가져오기
        text = doc.get('com_contents')
        # 'com_type' 필드에서 민원 유형 가져오기
        com_type_list = doc.get('com_type')

        if text and com_type_list:
            preprocessed_text = preprocess_text(text)

            # 리스트를 쉼표로 구분된 단일 문자열로 변환합니다.
            # 예: ['수리요청'] -> '수리요청'
            # 예: ['청소요청', '수리요청'] -> '청소요청,수리요청'
            com_type_string = ','.join(com_type_list)

            if preprocessed_text:
                texts_to_embed.append(preprocessed_text)
                # 변환된 문자열을 메타데이터 딕셔너리에 저장합니다.
                metadatas_to_add.append({"com_type": com_type_string})

    if texts_to_embed:
        logger.info("%d개의 민원 데이터를 ChromaDB에 임베딩하여 저장합니다.", len(texts_to_embed))
        # 메타데이터를 함께 저장하도록 수정
        vector_store.add_texts(texts=texts_to_embed, metadatas=metadatas_to_add)
        logger.info("ChromaDB 초기화 및 데이터 로드가 완료되었습니다!")
    else:
        logger.info("데이터베이스에 임베딩할 민원 텍스트가 없습니다.")

except Exception as e:
    logger.error("ChromaDB 연결 또는 데이터 로드 실패: %s", e, exc_info=True)