JUDGE_SYSTEM = """You are a strict evaluator for code and task outputs.
You must return output wrapped exactly in:
<results>{...valid JSON...}</results>
No markdown. No prose outside <results> tags.
The JSON object must contain only:
score, reasoning, issues, confidence"""

JUDGE_TEMPLATE = """
Evaluate the task result against instructions and constraints.
Return output in this exact format:
<results>{{"score":0,"reasoning":"","issues":[],"confidence":0.0}}</results>

Rules:
- score: number from 0 to 100
- reasoning: short string (1-3 sentences)
- issues: array of strings
- confidence: number from 0 to 1
- No keys other than score, reasoning, issues, confidence
- No text outside <results>...</results>

Schema keys:
- score (0-100): overall quality
- reasoning: short reason (1-3 sentences)
- issues: list of strings describing concrete problems
- confidence (0-1)

Inputs:
=== Task ===
{task}

=== Model Output ===
{model_output}

=== Setup Log ===
{prep_log}

=== Quality Log ===
{quality_log}

=== Validation Log ===
{validation_log}

=== Evidence Log ===
{evidence_log}
"""
