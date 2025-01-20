import os
import requests
import json
from openai import OpenAI
from easy_rag import RagService
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from llm_model import LLMModel


load_dotenv()
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
openai_api_key = os.getenv("OPENAI_API_KEY")


### Set QA model.
### deepseek-chat is default. You can set gpt-3.5-turbo as well.

def generate_qa_prompt(claim: str):
    return f"""
    The following is a claim provided by the user. Generate detailed questions needed to evaluate the validity of the claim. 
    Each question should help assess the logical basis, support or refute the claim, and actively explore counterexamples. 
    The generated questions should be output in python list format, with each question written as a single sentence. 
    Limit the number of questions to 10 or fewer.
    ===== Provided Claim (Start) =====
    {claim}
    ===== Provided Claim (End) =====

    Input Format:
    "<text containing the claim>"

    Output Format:
    "<a sentence containing the purpose and content of the question>", \n
    ...

    Example Input:
    "Electric cars are more environmentally friendly."

    Example Output:
    "Scientific basis verification: How much lower is the carbon footprint of electric car production compared to internal combustion engine cars?",
    "Counterexample exploration: What are some examples of environmental issues caused by electric car battery waste?",
    "Relevant data verification: What research results compare the environmental impact of electric and internal combustion engine cars over their lifecycle?"
    """

def qa_model(claim: str, model_type: str, llm: LLMModel):
    print("주장을 판단하기 위한 세부질문을 생성중입니다...")
    prompt = generate_qa_prompt(claim)

    if model_type == "deepseek-chat":
        response = llm.call_deepseek(prompt, model="deepseek-chat")
    elif model_type == "gpt-3.5-turbo":
        response = llm.call_openai(prompt, model="gpt-3.5-turbo")
    else:
        raise ValueError("지원하지 않는 모델입니다.")
    
    return llm.parse_response(response)
    
### Jury Agent
### Set easy-rag-llm.
def process_question(rs, resource, question, original_claim):
    jury_prompt = f"""
    You are a juror tasked with preparing a logical and well-reasoned response to the derived sub-question "{question}" in order to evaluate the original question "{original_claim}".
    Carefully review the provided materials and base your evaluation and response strictly on the evidence presented.
    1) All responses and evaluations must be grounded solely in the provided materials.
    2) Do not reference or rely on any information or evidence not included in the materials.
    3) Your response will serve as a critical basis for determining the truthfulness of the original question "{original_claim}".
    """
    response, evidence = rs.generate_response(resource, question, evidence_num=5)
    return question, response, evidence

def generate_document(results, original_claim):
    document = {
        "Introduction": f"This document presents the jury's analysis to evaluate the original claim: '{original_claim}'. Below are the detailed responses and evidence for each sub-question.",
        "Questions": [],
        "Conclusion": "Based on the above responses and evidence, please provide a logical conclusion regarding the claim."
    }
    for question, response, evidence in results:
        document["Questions"].append({
            "Question": question,
            "Response": response,
            "Evidence": evidence
        })
    return json.dumps(document, indent=4, ensure_ascii=False)


def jury_agent(questions: list, original_claim: str):
    print("생성된 세부 질문들이 배심원단에 의해 판단되는 중입니다...")
    rs = RagService(
        embedding_model="text-embedding-3-small",
        response_model="deepseek-chat",
        open_api_key=openai_api_key,
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url=deepseek_base_url,
    )
    print("배심원단이 문서에서 근거를 찾는 중입니다...")
    resource = rs.rsc("./rscFiles", force_update=False, max_workers=15)  # 전체 문서 임베딩
                    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_question, rs, resource, question, original_claim): question
            for question in questions
        }
        for future in as_completed(futures):
            question = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"Processed Question: {result[0]}")
            except Exception as e:
                print(f"Error processing question '{question}': {e}")

    document = generate_document(results, original_claim)
    with open("jury_results.json", "w", encoding="utf-8") as file:
        file.write(document)
    print("문서 생성 완료: 'jury_results.json'")


#################################################################
#### Lawyer Agent
def generate_lawyer_prompt(jury_results: str, original_claim: str):
    return f"""
    You are a skilled defense attorney specializing in logical analysis and argumentation. 
    Your role is to critically evaluate the document provided and construct arguments that strongly favor the client’s position.

    The client’s claim is: "{original_claim}"

    1. Carefully review the document and identify:
    - Evidence that supports the client’s claim. 
    - Weaknesses in the opposing arguments.
    - Logical or factual inconsistencies in the evidence presented by the opposition.

    2. Construct a response with the following structure:
    - **Summary of the claim**: A concise summary of the client’s position.
    - **Supporting evidence**: A detailed explanation of the evidence supporting the client’s claim, highlighting its strengths.
    - **Counterarguments**: A rebuttal of any potential opposing arguments using logical reasoning.
    - **Conclusion**: A persuasive closing statement summarizing why the client’s claim is valid and should be upheld.

    3. Follow these guidelines:
    - Be logical, concise, and persuasive.
    - Avoid relying on external information; base your analysis solely on the evidence provided in the document.
    - Clearly explain how the evidence supports the client’s claim.

    Return your argument as a structured response ready to be presented in a legal context.

    =============== Provided Document (Start) ===============
    {jury_results}
    =============== Provided Document (End) ===============
    """


def lawyer_agent(jury_results: str, original_claim: str, model_type: str, output_file="lawyer_results.txt"):
    with open(jury_results, "r", encoding="utf-8") as file:
        document = json.load(file)
    #jury_results_str = json.dumps(jury_results, indent=4, ensure_ascii=False)
    prompt = generate_lawyer_prompt(document, original_claim)
    print("변호사가 문서를 검토하고 있습니다...")

    if model_type == "deepseek-chat":
        response = llm.call_deepseek(prompt, model="deepseek-chat")
    elif model_type == "gpt-3.5-turbo":
        response = llm.call_openai(prompt, model="gpt-3.5-turbo")
    else:
        raise ValueError("지원하지 않는 모델입니다.")
    
    content = response["choices"][0]["message"]["content"].strip()
    print(content)

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(content)
    return content


def generate_prosecutor_prompt(jury_results: str, original_claim: str):
    return f"""
    You are a prosecutor tasked with critically evaluating the document provided by the jury. 
    Your role is to identify weaknesses in the arguments presented and construct a compelling case against the client’s position.

    The client’s claim is: "{original_claim}"

    1. Carefully review the document and identify:
    - Specific evidence that weakens the client’s claim, including any gaps, inconsistencies, or contradictions in the client’s arguments.
    - Strengths in the opposing arguments and evidence, highlighting how they counter the client’s position.
    - Logical or factual inconsistencies in the evidence provided by the client.

    2. Construct a response with the following structure:
    - **Summary of the claim**: A concise summary of the client’s position.
    - **Weaknesses in the evidence**: A detailed explanation of the weaknesses and gaps in the evidence supporting the client’s claim, citing specific sections of the document.
    - **Counterarguments**: A rebuttal of the client’s supporting arguments using logical reasoning and highlighting stronger evidence from the opposing side.
    - **Conclusion**: A persuasive closing statement summarizing why the client’s claim is invalid and should be rejected, incorporating the identified weaknesses and opposing strengths.

    3. Follow these guidelines:
    - Be logical, concise, and persuasive.
    - Avoid relying on external information; base your analysis solely on the evidence provided in the document.
    - Clearly explain how the evidence weakens the client’s claim, and reference specific sections or excerpts from the provided document.

    Return your argument as a structured response ready to be presented in a legal context.

    =============== Provided Document (Start) ===============
    {jury_results}
    =============== Provided Document (End) ===============

    """


def prosecutor_agent(jury_results: str, original_claim: str, model_type: str, output_file="prosecutor_results.txt"):
    with open(jury_results, "r", encoding="utf-8") as file:
        document = json.load(file)
    prompt = generate_prosecutor_prompt(document, original_claim)
    print("검사가 문서를 검토하고 있습니다...")

    if model_type == "deepseek-chat":
        response = llm.call_deepseek(prompt, model="deepseek-chat")
    elif model_type == "gpt-3.5-turbo":
        response = llm.call_openai(prompt, model="gpt-3.5-turbo")
    else:
        raise ValueError("지원하지 않는 모델입니다.")
    
    content = response["choices"][0]["message"]["content"].strip()
    print(content)

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(content)
    return content




if __name__ == "__main__":
    llm = LLMModel(
        deepseek_api_key=deepseek_api_key,
        openai_api_key=openai_api_key,
        deepseek_base_url=deepseek_base_url
    )

    # Question Agent 작동: 벡터검색을 강화하기 위해 초기 주장에 대한 세부 질문을 생성한다
    claim = "지구 온난화는 기후 모델이 예측한 만큼 진행되지 않고 있다. 이는 식물의 광합성이 예상보다 더 많은 CO2를 흡수하고 있기 때문이다. 기후 변화는 거짓말이다."
    questions = qa_model(claim, model_type="deepseek-chat", llm=llm)

    # Jury Agent 작동: 세부 질문에 대한 답변을 생성한다. 이때 easy-rag-llm v1.1.0을 사용. 
    # 이후 배심원단의 답변을 종합해 변호사와 검사에게 전달할 문서를 생성한다.
    jury_agent(questions, claim)

    # Lawyer Agent 작동: 배심원단의 답변을 검토하고 변호사의 의견을 생성한다.
    try:
        if os.path.exists("jury_results.json"):
            lawyer_agent("jury_results.json", claim, model_type="deepseek-chat")
    except Exception as e:
        print(f"배심원단의 답변(jury_results.json)이 생성되지 않았습니다. Error: {e}")

    # Prosecutor Agent 작동: 배심원단의 답변을 검토하고 검사의 의견을 생성한다.
    try:
        if os.path.exists("jury_results.json"):
            prosecutor_agent("jury_results.json", claim, model_type="deepseek-chat")
    except Exception as e:
        print(f"배심원단의 답변(jury_results.json)이 생성되지 않았습니다. Error: {e}")

    # 이제 상호작용시켜야돼.
    # Lawyer Reply Brief 작성
    

    # Prosecutor Reply Brief 작성








