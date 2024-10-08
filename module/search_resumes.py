from elasticsearch import Elasticsearch
import fasttext
import fasttext.util
import numpy as np
from nltk.tokenize import word_tokenize, sent_tokenize
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import CharacterTextSplitter
import fitz
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# FastText 모델 로드
fasttext.util.download_model('ko', if_exists='ignore')
ft_model = fasttext.load_model('cc.ko.300.bin')

# .env 파일에서 Elasticsearch 호스트 정보 가져오기
ELASTICSEARCH_HOST = os.getenv("elastic")
INDEX_NAME = "fasttext_search"

# Elasticsearch 연결
es = Elasticsearch([ELASTICSEARCH_HOST])

def vector_search(query, top_k=5000):
    query_vector = ft_model.get_sentence_vector(query)
    script_query = {
         "script_score": {
    "query": {
      "bool": {
        "should": [
          {
            "match": {
              "content": {
                "query": query,
                "boost": 1
              }
            }
          },
          {
            "term": {
              "content.keyword": {
                "value": query,
                "boost": 2
              }
            }
          },
          {
            "match": {
              "content.nori_mixed": {
                "query": query,
                "boost": 1.5
              }
            }
          },
          {
            "match_all": {}
          }
        ]
      }
    },
    "script": {
      "source": """
        double cosine_score = cosineSimilarity(params.query_vector, 'vector') + 1.0;
        double text_score = _score * 0.1;  // Adjust this multiplier as needed
        return cosine_score + text_score;  // Combine both scores
      """,
      "params": {"query_vector": query_vector.tolist()}
    }
  },
  
    }
    response = es.search(index=INDEX_NAME, body={"query": script_query, "size": top_k})
    return response['hits']['hits']


def search_result(query):
    results=vector_search(query)
    score_list = []
    for hit in results:
        # print(hit['_source']['source'])
        # print(hit['_source']['content'])
        # print(hit['_score'])
        new_entry = {
        "source": hit['_source']['source'],
        "score": hit['_score']
        
    }
    
    # 동일한 source가 있는지 확인
        if not any(entry['source'] == new_entry['source'] for entry in score_list):
            score_list.append(new_entry)
    
    return score_list

