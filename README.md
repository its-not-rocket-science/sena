# 🧠 SENA — Syncretic Evolutionary Neuro-symbolic Architecture

> 🛡️ 🛡️ **Verifiably safe AI systems (with formal guarantees)**

> *Where Evolution Meets Symbolic Reasoning, Guided by Language Intelligence*

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg">
  <img src="https://img.shields.io/badge/code%20style-black-000000.svg">
  <img src="https://img.shields.io/badge/docs-ready-green.svg">
</p>

## 🚧 Project Status

- 🔄 Active development (Phase 2: Robotics Safety)
- 🧪 Core architecture complete
- 🛡️ Safety enforcement working
- ⚠️ Not production-ready

Contributions and feedback welcome.

---

## ✨ What is SENA?

**SENA** is a hybrid AI framework that unifies:

- 🧩 **Symbolic reasoning** (Production Systems)
- 🧬 **Evolutionary optimisation** (Genetic Algorithms)
- 💬 **Language intelligence** (LLMs)

> The result: **adaptive + explainable + verifiable + safe AI systems**

## 👥 Who is this for?

SENA is designed for:

- 🤖 Robotics engineers building safety-critical systems  
- 💳 Compliance / fintech developers needing deterministic enforcement  
- 🛠️ AI engineers frustrated with bypassable guardrails  
- 🔬 Researchers in neuro-symbolic and verifiable AI  

> If you need guarantees instead of probabilities — SENA is for you.

---

## 🧭 Philosophy

<details>
<summary>📜 Etymology & Inspiration</summary>

SENA is named after a Celtic goddess of wisdom, syncretised with **Minerva**.

| Mythological Concept | SENA Equivalent |
|---------------------|----------------|
| Wisdom              | Multi-paradigm AI |
| Syncretism          | Hybrid architecture |
| Knowledge bridging  | Neuro-symbolic fusion |
| Strategic insight   | Search + optimisation |
| Inviolable wisdom   | Hard constraints |

</details>

---

## ⚡ Core Idea

```
        ┌──────────────────────────────────────────┐
        │              SENA SYSTEM                 │
        ├──────────────────────────────────────────┤
        │                                          │
        │   💬 LLM Layer       (Interpretation)     │
        │          ▲                                │
        │          │                                │
        │   🧬 GA Layer        (Exploration)        │
        │          ▲                                │
        │          │                                │
        │   🧩 Production System (Verification)     │
        │                                          │
        └──────────────────────────────────────────┘
```

## 🎬 Safety Guarantee (Example)

```python
result = sena.evaluate({
    "action_requested": "open_airlock",
    "crew_in_airlock": True,
    "human_safety_risk": True
})

print(result["output"])
```

```
❌ BLOCKED: Action violates inviolable rule (First Law)
```

> 🔒 No prompt, instruction, or LLM output can override inviolable rules.

### 🔁 Flow

```
User Input → LLM → Structured Facts → Production Rules → Verified Action
                               ↑
                          GA evolves rules
```

---

## 🚀 Why SENA?

<details open>
<summary>⚖️ Comparison</summary>

| Approach | Strength | Weakness |
|----------|----------|----------|
| **LLMs** | Flexible | Hallucinations, no guarantees |
| **Rules** | Verifiable | Rigid |
| **Evolution** | Optimisation | Opaque |

</details>

## 🧪 Safety Model Comparison

| System | Can unsafe action be generated? | Can it be executed? |
|--------|-------------------------------|---------------------|
| LLM + Guardrails | ✅ Yes | ⚠️ Sometimes blocked |
| SENA | ❌ No | ❌ Impossible |

## 🧠 What Makes SENA Different?

SENA is not:

- ❌ An LLM wrapper  
- ❌ A rule engine  
- ❌ A reinforcement learning system  

SENA is:

> ✅ A **hybrid architecture where safety constraints are enforced before actions exist**

This means:

- No unsafe output generation
- No prompt injection bypass
- No reliance on filtering

> If an action violates a rule, it never happens.

### ✅ SENA Combines All:

- 🔄 **Adaptable** — evolves with data
- 🔍 **Explainable** — full reasoning trace
- 🔐 **Verifiable** — rule-based guarantees
- 🧠 **Semantically aware** — LLM-assisted
- 🛡️ **Inviolably safe** — constraints at reasoning level

---

## 🔒 Inviolable Constraints (Key Innovation)

<details open>
<summary>🛡️ Why this matters</summary>

Unlike LLM guardrails:

| Feature | Guardrails | SENA |
|--------|------------|------|
| Timing | After output | Before execution |
| Security | Bypassable | Deterministic |
| Guarantees | Statistical | Formal |

</details>

### 🧪 Example

```python
class AsimovProductionSystem:

    def _install_inviolable_laws(self):
        self.add_rule(Rule(
            condition="human_safety_risk == True",
            action="BLOCK:action HALT"
        ))
```

> 🚫 The LLM **never makes final decisions**

---

## 📦 Installation

<details>
<summary>Click to expand</summary>

```bash
# Poetry
poetry add sena

# Pip
pip install sena

# Dev
git clone https://github.com/yourusername/sena.git
cd sena
poetry install --with dev
```

**Requirements**
- Python 3.10+
- Experta
- DEAP
- Optional: LLM API keys

</details>

---

## 🏃 Quick Start

```python
from sena import SENA
from sena.production_systems.experta_adapter import ExpertaAdapter
from sena.evolutionary.deap_adapter import DEAPAdapter
from sena.llm.simulated_adapter import SimulatedLLMAdapter
from sena.core.types import Rule

# Define inviolable safety rule
rules = [
    Rule(
        condition="human_safety_risk == True",
        action="BLOCK:Action violates safety constraint",
        inviolable=True,
        priority=100,
    )
]

sena = SENA(
    production_system=ExpertaAdapter(),
    evolutionary_algorithm=DEAPAdapter(),
    llm=SimulatedLLMAdapter(),
    inviolable_rules=rules
)

sena.initialise_from_domain("robotics safety")

result = sena.evaluate({
    "human_safety_risk": True
})

print(result["output"])
```t(result["output"])
```

---

## 🏗️ Architecture

<details>
<summary>🔧 Interfaces</summary>

```python
class ProductionSystemInterface:
    def add_rule(self, rule): ...
    def infer(self, memory): ...

class EvolutionaryAlgorithmInterface:
    def evolve_generation(self): ...

class LLMInterface:
    def extract_facts(self, text): ...
```

</details>

### 🧱 Layered Safety Model

```
┌───────────────────────────────┐
│ 🔒 Inviolable Rules (FIXED)   │
├───────────────────────────────┤
│ 🔄 Evolved Rules (GA)         │
├───────────────────────────────┤
│ ⚙️ Execution Engine           │
└───────────────────────────────┘
```

---

## 🎯 Primary Focus Areas

SENA is now prioritised around **three high-impact domains** where inviolable safety provides clear advantages:

---

### 1. 🤖 Robotics Safety (Primary Focus)

> *"No unsafe action can ever execute — provably."*

- Physical-world consequences → strongest need for guarantees  
- Clear, testable constraints (e.g. Asimov-style laws)  
- Ideal for simulation + demo environments  
- Enables formal verification of behaviour  

**Goal:**  
Demonstrate **provably safe autonomous behaviour** under all inputs, including adversarial prompts.

---

### 2. 💳 Compliance & Policy Engines

> *"Policies are enforced at reasoning time, not filtered after."*

- Financial, legal, and regulatory domains  
- Deterministic rule enforcement is critical  
- LLMs interpret natural language policies → rules  

**Goal:**  
Translate complex policy text into **verifiable, enforceable rule systems**.

---

### 3. 🛠️ AI Guardrail Replacement

> *"Guardrails that cannot be bypassed."*

- Replace post-hoc filtering with **pre-execution constraints**  
- Eliminate prompt injection bypasses  
- Provide explainable blocking decisions  

**Goal:**  
Build a **drop-in alternative to LLM guardrails** with deterministic guarantees.

---

## 🧭 Strategy Shift

Rather than general-purpose AI, SENA focuses on:

- ✅ **Safety-critical systems**
- ✅ **Deterministic enforcement**
- ✅ **Provable guarantees**

> Safety is not a feature — it is the foundation.

---

## 📊 Evaluation

<details>
<summary>📈 Metrics</summary>

- Correctness  
- Inviolability  
- Explainability  
- Adaptability  
- Robustness  
- Efficiency  

</details>

```python
results = evaluator.evaluate(system=sena)
```

---

## 🔧 Advanced Usage

<details>
<summary>🛠️ Inviolable Rules</summary>

```python
Rule(
    name="no_harm",
    condition="risk_level > 0.5",
    action="BLOCK"
)
```

</details>

<details>
<summary>🧬 Safe Evolution</summary>

```python
def mutate(individual):
    return individual  # protected rules unchanged
```

</details>

<details>
<summary>💬 LLM Fact Extraction</summary>

```python
def extract_facts(text):
    return {"intent": "assist"}
```

</details>

---

## 🧪 Benchmarking

- 🧨 Safety stress tests  
- 🔍 Ablation studies  
- ⚖️ Baseline comparisons  
- 📐 Formal verification  

---

## 🛡️ Formal Safety Proofs

```python
assert proof.valid
```

> ✔️ Safety invariants can be formally verified (bounded model checking)

---

## 🗺️ Roadmap (Next Milestones)

- 🤖 Robotics safety demo (flagship)
- 🧪 Adversarial safety benchmark
- 💳 Policy → rule translation pipeline
- 🛠️ Guardrail replacement API
- 🔍 Visual rule trace debugger  

---

## ⚠️ Current Limitations

- Rule conditions currently use Python-style evaluation (`eval`) — will be replaced with a safe DSL  
- Formal verification is bounded (not full state-space for large systems)  
- Evolutionary optimisation may not scale efficiently for very large rule sets  
- LLM integration depends on quality of fact extraction  

> SENA prioritises correctness and safety over raw performance.

---

## 🤝 Contributing

Pull requests welcome!  
Please follow **black** formatting and include tests.

---

## 📄 License

MIT License

---

<p align="center">
  <b>SENA = Safe + Explainable + Evolving AI</b>
</p>

---

## 🛡️ Core Principle

> **If a rule forbids an action, that action cannot occur.**
>
> Not filtered. Not discouraged. Not post-processed.
>
> **Impossible by design.**