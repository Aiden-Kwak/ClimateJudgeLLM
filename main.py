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
    - Evidence that supports the client’s claim. Be sure to include direct references to the original document, specifying the page number and any relevant quotes.
    - Weaknesses in the opposing arguments, providing specific references to the document where applicable.
    - Logical or factual inconsistencies in the evidence presented by the opposition, citing the document and page numbers for clarity.

    2. Construct a response with the following structure:
    - **Summary of the claim**: A concise summary of the client’s position.
    - **Supporting evidence**: A detailed explanation of the evidence supporting the client’s claim, highlighting its strengths. Include direct quotes and page numbers from the provided document and the document's name.
    - **Counterarguments**: A rebuttal of any potential opposing arguments using logical reasoning. Reference specific parts of the document and page numbers to strengthen your rebuttal.
    - **Conclusion**: A persuasive closing statement summarizing why the client’s claim is valid and should be upheld.

    3. Follow these guidelines:
    - Be logical, concise, and persuasive.
    - Avoid relying on external information; base your analysis solely on the evidence provided in the document.
    - Clearly explain how the evidence supports the client’s claim, and always cite the document name and page numbers to provide precise references like (document name / page).

    Return your argument as a structured response ready to be presented in a legal context.

    =============== Provided Document (Start) ===============
    {jury_results}
    =============== Provided Document (End) =================
    """


def lawyer_agent(jury_results: str, original_claim: str, model_type: str, output_file="./results/lawyer_results.txt"):
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
    #print(content)

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(content)
    return content


#################################################################
#### Prosecutor Agent

def generate_prosecutor_prompt(jury_results: str, original_claim: str):
    return f"""
    You are a prosecutor tasked with critically evaluating the document provided by the jury. 
    Your role is to identify weaknesses in the arguments presented and construct a compelling case against the client’s position.

    The client’s claim is: "{original_claim}"

    1. Carefully review the document and identify:
    - Specific evidence that weakens the client’s claim, including any gaps, inconsistencies, or contradictions in the client’s arguments. Provide direct references to the original document, including page numbers and relevant quotes.
    - Strengths in the opposing arguments and evidence, highlighting how they counter the client’s position. Reference the document and page numbers where applicable.
    - Logical or factual inconsistencies in the evidence provided by the client, citing specific excerpts and page numbers for clarity.

    2. Construct a response with the following structure:
    - **Summary of the claim**: A concise summary of the client’s position.
    - **Weaknesses in the evidence**: A detailed explanation of the weaknesses and gaps in the evidence supporting the client’s claim, citing specific sections, quotes, and page numbers from the document.
    - **Counterarguments**: A rebuttal of the client’s supporting arguments using logical reasoning and highlighting stronger evidence from the opposing side. Include specific references to the document and page numbers to substantiate your argument.
    - **Conclusion**: A persuasive closing statement summarizing why the client’s claim is invalid and should be rejected, incorporating the identified weaknesses and opposing strengths. Reference key evidence and page numbers to strengthen your conclusion.

    3. Follow these guidelines:
    - Be logical, concise, and persuasive.
    - Avoid relying on external information; base your analysis solely on the evidence provided in the document.
    - Clearly explain how the evidence weakens the client’s claim, and always cite the document name and page numbers to provide precise references like (document name / page).

    Return your argument as a structured response ready to be presented in a legal context.

    =============== Provided Document (Start) ===============
    {jury_results}
    =============== Provided Document (End) =================
    """

def prosecutor_agent(jury_results: str, original_claim: str, model_type: str, output_file="./results/prosecutor_results.txt"):
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
    #print(content)

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(content)
    return content


def generate_prosecutor_reply_brief_prompt(lawyer_results: str, output_file="./reply_brief/prosecutor_reply_brief.txt"):
    reply_brief = f"""
    You are a prosecutor tasked with constructing a reply brief that critically evaluates the defense’s arguments and provides a compelling case to refute them.

    The defense’s argument is summarized in the provided document. Your role is to:
    1. Identify critical weaknesses in the defense’s argument, focusing on:
    - Logical flaws or inconsistencies in their reasoning.
    - Weak or unsupported evidence cited by the defense.
    - Misrepresentation or misinterpretation of key evidence or facts.
    2. Construct a compelling rebuttal to the defense’s argument, emphasizing:
    - Strong evidence that contradicts or undermines the defense’s position.
    - Logical reasoning that invalidates the defense’s conclusions.
    - The strengths of the prosecution’s original case.
    3. Clearly explain how the evidence and reasoning refute the defense’s claims, referencing specific sections, excerpts, and page numbers from the provided document.

    ### **Structure of the Reply Brief**
    1. **Summary of the Defense’s Argument**:
    - Provide a concise and objective summary of the key points in the defense’s argument.
    2. **Critical Weaknesses**:
    - Identify and explain the weaknesses, flaws, or gaps in the defense’s argument or evidence. Reference the original document with page numbers.
    3. **Prosecutor’s Counterarguments**:
    - Present a rebuttal to each key point in the defense’s argument. Use strong evidence from the provided document and logical reasoning to strengthen the prosecution’s case. Include direct citations (e.g., “Document A, Page 12”).
    4. **Conclusion**:
    - Summarize why the defense’s argument is invalid and reiterate the strength of the prosecution’s case.

    ### **Guidelines**:
    - Be logical, concise, and persuasive.
    - Avoid relying on external information; base your analysis solely on the evidence provided in the document.
    - Support all claims with specific references to the provided document, including page numbers and relevant excerpts.

    =============== Provided Document (Start) ===============
    {lawyer_results}
    =============== Provided Document (End) ===============
    """
    return reply_brief

def prosecutor_reply_brief(lawyer_results: str, model_type: str, output_file="./reply_brief/prosecutor_reply_brief.txt"):
    with open(lawyer_results, "r", encoding="utf-8") as file:
        #document = json.load(file), json으로 작성할 필요 없어
        document = file.read().strip()
    prompt = generate_prosecutor_reply_brief_prompt(document)
    print("검사가 변호사의 의견을 검토하고 있습니다...")


    if model_type == "deepseek-chat":
        response = llm.call_deepseek(prompt, model="deepseek-chat")
    elif model_type == "gpt-3.5-turbo":
        response = llm.call_openai(prompt, model="gpt-3.5-turbo")
    else:
        raise ValueError("지원하지 않는 모델입니다.")
    
    content = response["choices"][0]["message"]["content"].strip()

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(content)
    return content

def generate_lawyer_reply_brief_prompt(prosecutor_results: str, original_claim: str, output_file="./reply_brief/lawyer_reply_brief.txt"):
    reply_brief = f"""
    You are a skilled defense attorney tasked with constructing a reply brief to refute the prosecutor’s arguments and strengthen the client’s position. 
    Your role is to critically evaluate the prosecutor’s claims and evidence, identify weaknesses, and construct a compelling rebuttal in support of the client’s position.

    The client’s claim is: "{original_claim}"

    1. Carefully review the prosecutor’s arguments provided in the document and perform the following tasks:
    - Identify logical flaws, inconsistencies, or gaps in the prosecutor’s arguments and evidence.
    - Highlight the strengths of the client’s position, including evidence that contradicts the prosecutor’s claims.
    - Emphasize any misinterpretations, overgeneralizations, or unsupported assumptions made by the prosecutor.

    2. Construct a reply brief with the following structure:
    - **Summary of the Prosecutor’s Arguments**: Provide a concise and objective summary of the prosecutor’s key points.
    - **Weaknesses in the Prosecutor’s Arguments**: Identify and explain the weaknesses, flaws, or gaps in the prosecutor’s claims and evidence. Reference specific sections, excerpts, and page numbers from the provided document.
    - **Defense’s Rebuttal**: Present a detailed rebuttal to each key point made by the prosecutor, using strong evidence and logical reasoning to support the client’s claim. Include specific references to the document, citing page numbers and quotes where applicable.
    - **Strengthening the Client’s Position**: Reiterate the strongest evidence and arguments supporting the client’s claim, demonstrating why it remains valid despite the prosecutor’s criticisms.
    - **Conclusion**: Provide a persuasive closing statement summarizing why the prosecutor’s arguments are insufficient and why the client’s claim should be upheld.

    3. Follow these guidelines:
    - Be logical, concise, and persuasive.
    - Avoid relying on external information; base your arguments solely on the evidence provided in the document.
    - Clearly explain how the evidence supports the client’s claim and weakens the prosecutor’s arguments.
    - Include direct references to the provided document, specifying page numbers and relevant quotes to substantiate your points.

    =============== Provided Document (Start) ===============
    {prosecutor_results}
    =============== Provided Document (End) ===============
    """
    return reply_brief

def lawyer_reply_brief(prosecutor_results: str, original_claim: str, model_type: str, output_file="./reply_brief/lawyer_reply_brief.txt"):
    with open(prosecutor_results, "r", encoding="utf-8") as file:
        #document = json.load(file)
        document = file.read().strip() 
    prompt = generate_lawyer_reply_brief_prompt(document, original_claim)
    print("변호사가 검사의 의견을 검토하고 있습니다...")

    if model_type == "deepseek-chat":
        response = llm.call_deepseek(prompt, model="deepseek-chat")
    elif model_type == "gpt-3.5-turbo":
        response = llm.call_openai(prompt, model="gpt-3.5-turbo")
    else:
        raise ValueError("지원하지 않는 모델입니다.")
    
    content = response["choices"][0]["message"]["content"].strip()

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(content)
    return content

### MEMO ###
"""
검사는 변호사의 논리를 반박하는게 중요하지만, 변호사는 검사의 논리를 반박하는 것 뿐 아니라 의뢰인의 의견을 강화하는게 중요함.
"""

import json
import os

def create_judge_input(jury_path, lawyer_path, lawyer_reply_path, prosecutor_path, prosecutor_reply_path, output_path):
    try:
        with open(jury_path, "r", encoding="utf-8") as jury_file:
            jury_results = json.load(jury_file)
        
        with open(lawyer_path, "r", encoding="utf-8") as lawyer_file:
            lawyer_results = lawyer_file.read().strip()
        
        with open(lawyer_reply_path, "r", encoding="utf-8") as lawyer_reply_file:
            lawyer_reply = lawyer_reply_file.read().strip()
        
        with open(prosecutor_path, "r", encoding="utf-8") as prosecutor_file:
            prosecutor_results = prosecutor_file.read().strip()
        
        with open(prosecutor_reply_path, "r", encoding="utf-8") as prosecutor_reply_file:
            prosecutor_reply = prosecutor_reply_file.read().strip()
        
        judge_input = {
            "jury_results": jury_results,
            "lawyer_results": lawyer_results,
            "lawyer_reply_brief": lawyer_reply,
            "prosecutor_results": prosecutor_results,
            "prosecutor_reply_brief": prosecutor_reply
        }

        with open(output_path, "w", encoding="utf-8") as output_file:
            json.dump(judge_input, output_file, indent=4, ensure_ascii=False)
        
        print(f"판사 에이전트 입력 데이터가 생성되었습니다: {output_path}")
    except Exception as e:
        print(f"데이터 통합 중 오류 발생: {e}")


####### 판사 에이전트 #######
def generate_judge_prompt(judge_input: str):
    return f"""
    You are a judge tasked with reviewing the arguments and evidence provided by both the defense and the prosecution to reach a fair and logical verdict. 
    Your role is to:
    1. Analyze the jury's evaluation of the claim.
    2. Critically assess the arguments and rebuttals presented by both the defense and the prosecution.
    3. Weigh the strengths and weaknesses of each side's arguments based on the evidence provided.

    Your verdict must:
    1. Summarize the key points from both sides.
    2. Identify which side has presented a stronger case, supported by specific reasoning and evidence.
    3. Conclude with a logical and fair judgment, stating whether the client’s claim is valid or not.

    You are only allowed to base your analysis on the following provided document. Avoid using external information.

    =============== Provided Document (Start) ===============
    {judge_input}
    =============== Provided Document (End) ===============

    Your response must be structured as follows:
    1. **Summary of the Case**: Provide an objective summary of the client’s claim and the arguments presented by both sides.
    2. **Analysis**:
    - Strengths and weaknesses of the defense’s arguments.
    - Strengths and weaknesses of the prosecution’s arguments.
    3. **Verdict**: State your final judgment and provide a concise explanation of your reasoning.
    """

def judge_agent(judge_input_path, model_type="deepseek-chat"):
    try:
        with open(judge_input_path, "r", encoding="utf-8") as file:
            judge_input = json.load(file)
        judge_prompt = json.dumps(judge_input, indent=4, ensure_ascii=False)
        prompt = generate_judge_prompt(judge_input)

        print("판사 에이전트가 판결을 생성중입니다...")
        if model_type == "deepseek-chat":
            response = llm.call_deepseek(prompt, model="deepseek-chat")
        elif model_type == "gpt-3.5-turbo":
            response = llm.call_openai(prompt, model="gpt-3.5-turbo")
        else:
            raise ValueError("지원하지 않는 모델입니다.")

        content = response["choices"][0]["message"]["content"].strip()
        print("판결 생성 완료:")
        print(content)

        # 결과 저장
        with open("judge_verdict.txt", "w", encoding="utf-8") as file:
            file.write(content)

    except Exception as e:
        print(f"판사 에이전트 실행 중 오류 발생: {e}")





if __name__ == "__main__":

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RESULTS_DIR = os.path.join(BASE_DIR, "results")
    REPLY_BRIEF_DIR = os.path.join(BASE_DIR, "reply_brief")

    print("경로확인: ", RESULTS_DIR)

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
    if os.path.exists("jury_results.json"):
        print("기존 생성된 배심원단의 답변(jury_results.json)을 사용합니다.")
        pass
    else:
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
    try:
        if os.path.exists("./results/prosecutor_results.txt"):
            PROSECUTOR_RESULT_PATH = os.path.join(RESULTS_DIR, "prosecutor_results.txt")
            print("변호사의 의견을 검사에게 전달하고 있습니다...")
            lawyer_reply_brief(PROSECUTOR_RESULT_PATH, claim, model_type="deepseek-chat")
    except Exception as e:
        print(f"검사의 의견(prosecutor_results.txt)이 생성되지 않았습니다. Error: {e}")

    # Prosecutor Reply Brief 작성
    try:
        if os.path.exists("./results/lawyer_results.txt"):
            LAWYER_RESULT_PATH = os.path.join(RESULTS_DIR, "lawyer_results.txt")
            print("검사의 의견을 변호사에게 전달하고 있습니다...")
            prosecutor_reply_brief(LAWYER_RESULT_PATH, model_type="deepseek-chat")
    except Exception as e:
        print(f"변호사의 의견(lawyer_results.txt)이 생성되지 않았습니다. Error: {e}")

    # 판사한테 검토시켜야할 문서가 5개. 이거 전부 단일 에이전트의 논리가 감당할 수 있는지 확인해야돼. 
    # 1차로 5개, 2차로 jury 제외한 4개로 테스트해보자
    # 전체 내용을 json으로 구조화해서 입력하자.
    create_judge_input(
        jury_path="jury_results.json",
        lawyer_path="./results/lawyer_results.txt",
        lawyer_reply_path="./reply_brief/lawyer_reply_brief.txt",
        prosecutor_path="./results/prosecutor_results.txt",
        prosecutor_reply_path="./reply_brief/prosecutor_reply_brief.txt",
        output_path="judge_input.json"
    )

    # 판사 에이전트 작동
    judge_agent("judge_input.json", model_type="deepseek-chat")









