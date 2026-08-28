from app.application.decision_config import DecisionThresholdConfig
from app.domain.intelligence import DirectionalBias, DecisionReport, AnalysisBundle

class ModePolicyResult:
    def __init__(self, actionable: bool, threshold: int, reason: str):
        self.actionable = actionable
        self.threshold = threshold
        self.reason = reason

class ModeExecutionPolicy:
    def __init__(self, config: DecisionThresholdConfig):
        self.config = config

    def evaluate(
        self, 
        mode: str, 
        confidence: int, 
        bias: DirectionalBias, 
        decision: DecisionReport, 
        bundle: AnalysisBundle
    ) -> ModePolicyResult:
        
        has_high_risk = any(r.severity.name in ("HIGH", "CRITICAL") for r in decision.risk_summary)
        
        # If bias is already NEUTRAL/WAIT from underlying engine, we NEVER override it to actionable.
        # "If existing risk filter says trade is forbidden, mode policy cannot turn WAIT into BUY."
        if bias == DirectionalBias.NEUTRAL:
            return ModePolicyResult(
                actionable=False,
                threshold=0,
                reason="Underlying intelligence and risk filter generated WAIT. Policy cannot override."
            )
            
        if has_high_risk:
            return ModePolicyResult(
                actionable=False,
                threshold=0,
                reason="Existing high/critical risks block execution regardless of mode."
            )
            
        expected_move_val = 0
        if decision.expected_move and decision.expected_move.min_usd is not None:
            expected_move_val = float(decision.expected_move.min_usd)

        if mode == "physical":
            min_move = float(self.config.physical_minimum_expected_move_usd)
            if expected_move_val < min_move:
                return ModePolicyResult(
                    False,
                    self.config.physical_action_threshold,
                    f"Expected move ${expected_move_val:g} is below Physical minimum ${min_move:g}."
                )
            if decision.opportunity_score < self.config.physical_minimum_opportunity_score:
                return ModePolicyResult(
                    False,
                    self.config.physical_action_threshold,
                    f"Physical opportunity score {decision.opportunity_score} is below required {self.config.physical_minimum_opportunity_score}."
                )
            if decision.investment_score < self.config.physical_minimum_investment_score:
                return ModePolicyResult(
                    False,
                    self.config.physical_action_threshold,
                    f"Physical investment score {decision.investment_score} is below required {self.config.physical_minimum_investment_score}."
                )

            threshold = self.config.physical_action_threshold
            if confidence >= threshold:
                return ModePolicyResult(True, threshold, "Physical policy conditions met.")
            else:
                return ModePolicyResult(
                    False, 
                    threshold, 
                    f"Physical confidence {confidence}% is below required {threshold}%."
                )
                
        elif mode == "forex":
            min_move = float(self.config.forex_minimum_expected_move_usd)
            if expected_move_val < min_move:
                return ModePolicyResult(
                    False,
                    self.config.forex_action_threshold,
                    f"Expected move ${expected_move_val:g} is below Forex minimum ${min_move:g}."
                )
            if decision.opportunity_score < self.config.forex_minimum_opportunity_score:
                return ModePolicyResult(
                    False,
                    self.config.forex_action_threshold,
                    f"Forex opportunity score {decision.opportunity_score} is below required {self.config.forex_minimum_opportunity_score}."
                )
            if decision.investment_score < self.config.forex_minimum_investment_score:
                return ModePolicyResult(
                    False,
                    self.config.forex_action_threshold,
                    f"Forex investment score {decision.investment_score} is below required {self.config.forex_minimum_investment_score}."
                )

            threshold = self.config.forex_action_threshold
            high_threshold = self.config.forex_high_confidence_threshold
            
            if confidence < threshold:
                return ModePolicyResult(
                    False, 
                    threshold, 
                    f"Forex policy requires >={threshold}% conviction; current conviction {confidence}%."
                )
            
            # 60-70 requires acceptable technical alignment and acceptable existing risk/reward
            if threshold <= confidence < high_threshold:
                # Acceptable technical alignment: bias matches technical bias
                tech_aligned = bundle.technical.bias == bias
                
                # Acceptable risk/reward: expected move > 0
                has_reward = expected_move_val > 0
                    
                if tech_aligned and has_reward:
                    return ModePolicyResult(True, threshold, "Forex policy conditions met (acceptable technicals and reward).")
                else:
                    return ModePolicyResult(
                        False, 
                        threshold, 
                        f"Forex policy permits action from {threshold}%, but technical/risk conditions are insufficient."
                    )
            
            # >= high_threshold (70)
            return ModePolicyResult(True, threshold, "Forex policy high-confidence conditions met.")
            
        elif mode == "etf":
            min_move = float(self.config.etf_minimum_expected_move_usd)
            if expected_move_val < min_move:
                return ModePolicyResult(
                    False,
                    self.config.etf_action_threshold,
                    f"Expected move ${expected_move_val:g} is below ETF minimum ${min_move:g}."
                )
            if decision.opportunity_score < self.config.etf_minimum_opportunity_score:
                return ModePolicyResult(
                    False,
                    self.config.etf_action_threshold,
                    f"ETF opportunity score {decision.opportunity_score} is below required {self.config.etf_minimum_opportunity_score}."
                )
            if decision.investment_score < self.config.etf_minimum_investment_score:
                return ModePolicyResult(
                    False,
                    self.config.etf_action_threshold,
                    f"ETF investment score {decision.investment_score} is below required {self.config.etf_minimum_investment_score}."
                )

            threshold = self.config.etf_action_threshold
            if confidence >= threshold:
                # require macro/institutional confirmation where existing signals are available
                macro_ok = bundle.fundamental.bias in (bias, DirectionalBias.NEUTRAL)
                inst_ok = bundle.institutional.bias in (bias, DirectionalBias.NEUTRAL)
                if macro_ok and inst_ok:
                    return ModePolicyResult(True, threshold, "ETF policy conditions met.")
                else:
                    return ModePolicyResult(
                        False, 
                        threshold, 
                        f"ETF policy requires >={threshold}% conviction and supporting macro/institutional conditions."
                    )
            else:
                return ModePolicyResult(
                    False, 
                    threshold, 
                    f"ETF policy requires >={threshold}% conviction; current conviction {confidence}%."
                )
                
        # Default fallback
        return ModePolicyResult(True, 0, "No strict policy applied.")
