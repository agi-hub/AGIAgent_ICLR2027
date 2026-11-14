# Wiki-Evolve vs All Baselines — Results Summary

> 6 games × 10 episodes × 110 steps | GLM-5.2 backbone (ours), Gemini backbone (baselines)
>
> 日期: 2026-08-02

---

## Table 1: Absolute Average Scores (over 10 episodes)

| Game (max) | Wiki-Evolve<br>(GLM-5.2) | Wiki-Evolve<br>(DeepSeek-Pro) | EvoTest<br>(GLM-5.2) | EvoTest<br>(Gemini) | EvoPrompt<br>(Gemini) | Reflexion<br>(Gemini) | GRPO<br>(Gemini) | Memory<br>(Gemini) | Static<br>(Gemini) |
|---|---|---|---|---|---|---|---|---|---|
| Detective (360) | **297.0** | 221.0 | 250.0 | 266.0 | 138.0 | 119.0 | 54.0 | 80.0 | 22.0 |
| Library (30) | 29.1 | **29.8** | 11.7 | 14.1 | 13.3 | 12.4 | 13.4 | 11.5 | 10.0 |
| Zork1 (350) | **61.6** | 35.5 | 46.0 | 34.4 | 21.5 | 18.5 | 15.0 | 17.0 | 9.5 |
| Zork3 (7) | 3.6 | **3.8** | 2.6 | 2.2 | 1.6 | 1.2 | 1.0 | 0.9 | 0.1 |
| Balances (51) | 19.5 | **20.5** | 17.0 | 8.0 | 9.0 | 8.4 | 9.7 | 9.4 | 7.5 |
| Temple (35) | **22.0** | 15.0 | 8.0 | 5.8 | 6.2 | 5.5 | 6.3 | 6.1 | 4.5 |
| **TOTAL avg** | **72.1** | **54.3** | **55.9** | **55.1** | **31.6** | **27.5** | **16.6** | **20.8** | **8.9** |

---

## Table 2: Normalized Scores (% of game max, averaged)

| Game (max) | Wiki-Evolve<br>(GLM-5.2) | Wiki-Evolve<br>(DeepSeek-Pro) | EvoTest<br>(GLM-5.2) | EvoTest<br>(Gemini) | EvoPrompt<br>(Gemini) | Reflexion<br>(Gemini) | GRPO<br>(Gemini) | Memory<br>(Gemini) | Static<br>(Gemini) |
|---|---|---|---|---|---|---|---|---|---|
| Detective (360) | **82.5%** | 61.4% | 69.4% | 73.9% | 38.3% | 33.1% | 15.0% | 22.2% | 6.1% |
| Library (30) | 97.0% | **99.3%** | 39.0% | 47.0% | 44.3% | 41.3% | 44.7% | 38.3% | 33.3% |
| Zork1 (350) | **17.6%** | 10.1% | 13.1% | 9.8% | 6.1% | 5.3% | 4.3% | 4.9% | 2.7% |
| Zork3 (7) | 51.4% | **54.3%** | 37.1% | 31.4% | 22.9% | 17.1% | 14.3% | 12.9% | 1.4% |
| Balances (51) | 38.2% | **40.2%** | 33.3% | 15.7% | 17.6% | 16.5% | 19.0% | 18.4% | 14.7% |
| Temple (35) | **62.9%** | 42.9% | 22.9% | 16.6% | 17.7% | 15.7% | 18.0% | 17.4% | 12.9% |
| **Avg %** | **58.3%** | **51.4%** | **35.8%** | **32.4%** | **24.5%** | **21.5%** | **19.2%** | **19.0%** | **11.9%** |

---

## Key Findings

1. **Wiki-Evolve (GLM-5.2) ranks #1** with 58.3% average normalized score, followed by Wiki-Evolve (DeepSeek-Pro) at 51.4%.
2. **Wiki-Evolve outperforms EvoTest (same GLM-5.2 backbone)** by a large margin: 58.3% vs 35.8% (+22.5pp).
3. **Detective** is the highest-scoring game for our method (82.5%), demonstrating strong knowledge-guided path execution.
4. **Library** is nearly solved by both our backbones (97-99%), while baselines plateau at 33-47%.
5. **Zork1** shows our largest relative advantage: 17.6% vs EvoTest's 13.1% and Static's 2.7%.
6. **Static** (no learning) consistently performs worst (11.9%), confirming the value of test-time learning.
