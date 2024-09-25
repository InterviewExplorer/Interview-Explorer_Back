from datetime import datetime, timedelta

import requests
import os
from bs4 import BeautifulSoup
from transformers import BertTokenizer, BertModel
import torch
from elasticsearch import Elasticsearch
import random
from dotenv import load_dotenv
import json
from openai import OpenAI

# Load environment variables
load_dotenv()

# 설정
ELASTICSEARCH_HOST = os.getenv("elastic")
API_KEY = os.getenv("API_KEY")
GPT_MODEL = os.getenv("gpt")

if API_KEY is None:
    raise ValueError("API_KEY가 없습니다.")
if GPT_MODEL is None:
    raise ValueError("GPT_Model이 없습니다.")

client = OpenAI(api_key=API_KEY)

# Elasticsearch 클라이언트 설정
es = Elasticsearch([ELASTICSEARCH_HOST])

# BERT 모델 및 토크나이저 불러오기
tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
model = BertModel.from_pretrained('bert-base-uncased')

# 현재 날짜 가져오기
# def get_random_date_within_days(days):
#     today = datetime.now()
#     random_days = random.randint(0, days)
#     random_date = today - timedelta(days=random_days)
#     return random_date.strftime("%Y.%m.%d")

def get_dates_within_days(days):
    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime("%Y.%m.%d") for i in range(days + 1)]
    return dates

# 질문을 벡터로 변환하는 함수
def get_vector(text):
    inputs = tokenizer(text, return_tensors='pt')
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.last_hidden_state[0][0].numpy()

# Elasticsearch에서 벡터 기반 검색을 수행하는 함수
def searchDocs_generate(query, index_name, type):
    should_queries = []  # should_queries 리스트 초기화

    if type == 'behavioral':
        # 현재 날짜로부터 3일 전까지의 날짜 리스트 생성
        date_list = get_dates_within_days(2)
        query = " ".join(date_list)
        print("query: ", query)

        # 날짜를 포함한 쿼리 작성
        should_queries.extend([
            {
                "match": {
                    "question": {
                        "query": date,
                        "fuzziness": "AUTO"
                    }
                }
            } for date in date_list
        ])

    # 기본 쿼리 추가
    should_queries.append({
        "match": {
            "question": {
                "query": query,
                "fuzziness": "AUTO"
            }
        }
    })

    # 쿼리를 벡터로 변환
    query_vector = get_vector(query).tolist()

    response = es.search(
        index=index_name,
        body={
            "query": {
                "bool": {
                    "should": should_queries + [
                        {
                            "script_score": {
                                "query": {
                                    "match_all": {}
                                },
                                "script": {
                                    "source": "cosineSimilarity(params.query_vector, 'vector') + 1.0",
                                    "params": {
                                        "query_vector": query_vector
                                    }
                                }
                            }
                        }
                    ]
                }
            },
            "size": 10  # 관련 문서 10개를 가져옴
        }
    )

    hits = response['hits']['hits']
    return [hit['_source']['question'] for hit in hits]

def generate_questions(job, type, combined_context, num_questions):
    if type == "technical":
        prompt = f"""
        # Role
        You are the interviewer.

        # Task
        Create {num_questions} technical questions based on the following criteria:
        - User role: {job}
        - Context: {combined_context}

        # Instructions
        - Generate questions to assess the level of interest in new technologies related to {job}.
        - The questions should focus on concepts or the degree of interest.
        - Specify the name of a newly released technology in each question.
        - Please ask questions that focus solely on the concept of the technology, and if the interviewee has any information about it, request them to explain.
        - Provide a brief explanation of the presented technology, then ask a derived question.

        # Example
        - Have you come across any technologies or papers recently that you found interesting or enjoyable?
        - How do you think the free availability of MLOps platforms positively impacts the developer community?
        - Have you heard of OpenAI's 'Strawberry' project?
        - Have you heard of the recently announced 'Mistral NeMo'? If you know anything about 'Mistral NeMo,' please explain it.
        - What do you think about the impact of AI model price reductions on developers?

        # Policy
        - Generate {num_questions} unique questions
        - Questions should be answerable through verbal explanation.
        - Write your questions in Korean only.
        - Do not ask for code examples.
        - You must strictly adhere to the following JSON format.
        - Only include the values corresponding to the questions in the output format.
        - Do not include any other text, numbers, or explanations.
        - Refer to users as '면접자'.
        - Please append the following sentence in Korean to the end of all questions: 'If you do not know this technology, please tell me about a technology or paper you have recently found interesting.'

        # Output Format
        {{
            "Questions": [
                ""
                ...
            ]
        }}
        """
    elif type == "behavioral":
        prompt = f"""
        # Role
        You are the interviewer.

        # Task
        Create {num_questions} behavioral questions based on the following criteria:
        - Context: {combined_context}

        # Instructions
        - To assess the interviewer's personality and opinions, you must write {num_questions} unique, non-overlapping questions.        
        - Each question should be clearly structured and include detailed background information on recent social issues.
        - Questions should refer to specific news events and clearly state the news source or background.
        - The interviewee may not be familiar with current social issues, so before asking questions, you should explain in detail what is being discussed and include additional explanations of relevant keywords.
        - Questions should focus on assessing how the interviewee perceives the social issue.
        - Questions should encourage the interviewee to express their thoughts through verbal explanations.
        - The difficulty level of the questions should be such that the interviewee can answer even if they do not know much about the news.
        - Questions must be consistent with the title and content of the news.
        - When creating questions, you should not mention the interviewee's occupation.
        - The topic of the question must be a unique news topic that does not overlap.
        - The questions you ask should focus on "What do you think?" rather than whether the interviewee knows this, and should be made so that even kindergarteners can answer.

        # Policy
        - Write your questions in Korean only.
        - You must strictly adhere to the following JSON format.
        - Only include the values corresponding to the questions in the output format.
        - Refer to users as '면접자'.
         
        # Example
        - Recently, AI technology is being used to interpret health checkup results. What are your thoughts on the positive impact these technologies are having on personal health management? And what do you think are the ethical issues that may arise in this regard?
        - Naver is collaborating with Saudi Arabia to develop an Arabic-based macrolanguage model. What are your thoughts on the impact of global collaboration on technological advancement?
        - T Map has launched an AI location recommendation service. What do you think about the impact of AI on our choices and the problems it may cause?
        - It is said that a smart speaker developed by KAIST can help manage mental health. What are your thoughts on the impact of technology on a person’s mental health?
        - SK Hynix has installed its memory solution into open source Linux. What are your thoughts on the impact of open source technology on industry development?

        # Output Format
        {{
            "Questions": [
                ""
                ...
            ]
        }}
        """
    else:
        raise ValueError("Invalid type provided. Must be 'technical' or 'behavioral'.")

    completion = client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": "You are a professional interviewer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    response_content = completion.choices[0].message.content
    print("response_content", response_content)

    try:
        result = json.loads(response_content)

        if isinstance(result, dict) and "Questions" in result:
            questions = result["Questions"]

            # questions 필드가 문자열인 경우
            if isinstance(questions, str):
                questions_list = json.loads(questions)
            # questions 필드가 리스트인 경우
            elif isinstance(questions, list):
                questions_list = questions
            else:
                return {"error": "Questions 필드의 형식이 올바르지 않습니다."}

            # 리스트에서 랜덤으로 하나 선택
            if questions_list:
                selected_question = random.choice(questions_list)
                return {"Questions": selected_question}
            else:
                return {"Questions": "질문이 없습니다."}

        return {"error": "Questions 필드가 없거나 예상된 형식이 아닙니다."}

    except json.JSONDecodeError as e:
        return {"error": f"JSON 파싱 오류: {e}"}

# 크롤링 데이터 랜덤으로 가져오기
def get_random_samples(data, sample_size=10):
    return random.sample(data, min(sample_size, len(data)))

# 새로운 질문을 생성하는 함수
def create_newQ(job: str, type: str) -> dict:
    # type에 따라 INDEX_NAME 변경
    if type == 'technical':
        index_name = 'new_technology'
    elif type == 'behavioral':
#          index_name = 'new_personality'
        index_name = 'test_rag_behavioral'
    else:
        return {"error": "잘못된 type 값입니다. 'technical' 또는 'behavioral' 중 하나여야 합니다."}

    related_docs = searchDocs_generate(job, index_name, type)
    # print("related_docs", related_docs)

    if related_docs:
        random_samples = get_random_samples(related_docs, sample_size=10)
        combined_context = " ".join(random_samples)
        num_questions = 10
        questions = generate_questions(job, type, combined_context, num_questions)

        return questions
    else:
        return {"Questions": ["문서를 찾지 못했습니다."]}
