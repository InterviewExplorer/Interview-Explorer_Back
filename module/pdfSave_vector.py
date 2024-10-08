import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
import fasttext
import fasttext.util
import numpy as np

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import CharacterTextSplitter
import fitz
fasttext.util.download_model('ko', if_exists='ignore')
ft_model = fasttext.load_model('cc.ko.300.bin')

# .env 파일 로드
load_dotenv()

# .env 파일에서 Elasticsearch 호스트 정보 가져오기
ELASTICSEARCH_HOST = os.getenv('elastic')

INDEX_NAME = "fasttext_search"
# Elasticsearch 연결
es = Elasticsearch([ELASTICSEARCH_HOST])
def add_resumes(source,resume_name):
       

            text=read_pdf(source)
            # print(text)
            text = text.replace('\n', ' ').strip()
            
            # sents=split_text_into_words(text)
            sents=text.split()
            # print(sents)
            add_doccument(sents,resume_name)

def read_pdf(file_path):
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text


def split_text(text):
    text_splitter = CharacterTextSplitter(
        separator = '.',
        chunk_size = 10,
        chunk_overlap = 3,
        length_function = len,
    )
    return text_splitter.split_text(text)
def is_non_zero_vector(vector):
    return np.any(vector != 0)



def add_doccument(text,title):
    # 문서 내용의 평균 벡터 계산
    next_id = get_next_id(INDEX_NAME)
    
    for i, content in enumerate(text, start=next_id):
        
        content = content.replace('\n', '').replace(',', '').strip()
        vectors = ft_model.get_sentence_vector(content)
        if is_non_zero_vector(vectors):

    
            doc = {
                "source": title,
                "content": content,
                "vector": vectors.tolist()
            }
            es.index(index=INDEX_NAME, body=doc, id=i)
        else : 
            print(f"Skipping document {content}: Zero vector")

def get_next_id(index_name):
    response = es.count(index=index_name)
    return response['count']