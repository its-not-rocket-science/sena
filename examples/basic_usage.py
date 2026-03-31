
from sena.orchestrator.sena import SENA
from sena.production_systems.experta_adapter import ExpertaAdapter
from sena.evolutionary.deap_adapter import DEAPAdapter
from sena.llm.simulated_adapter import SimulatedLLMAdapter

ps = ExpertaAdapter()
ea = DEAPAdapter()
llm = SimulatedLLMAdapter()

sena = SENA(ps, ea, llm)

sena.initialise_from_domain("test")

sena.train([])

result = sena.evaluate({"x": 1})
print(result)
