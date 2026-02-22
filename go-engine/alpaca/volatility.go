package alpaca

import "math"

// AnnualizedVolatility computes volatility from daily close prices.
// Bars should be in chronological order (oldest first). Uses log returns
// and annualizes with 252 trading days. Returns NaN if insufficient data.
func AnnualizedVolatility(bars []Bar) float64 {
	if len(bars) < 2 {
		return math.NaN()
	}
	var sum, sumSq float64
	n := float64(len(bars) - 1)
	for i := 1; i < len(bars); i++ {
		if bars[i-1].Close <= 0 {
			continue
		}
		logRet := math.Log(bars[i].Close / bars[i-1].Close)
		sum += logRet
		sumSq += logRet * logRet
	}
	if n < 2 {
		return math.NaN()
	}
	variance := (sumSq - sum*sum/n) / (n - 1)
	if variance <= 0 {
		return 0
	}
	// Annualize: multiply daily std dev by sqrt(252)
	return math.Sqrt(variance * 252)
}
