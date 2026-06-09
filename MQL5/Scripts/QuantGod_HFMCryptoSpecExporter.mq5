#property strict
#property script_show_inputs

input string ExportFolderName = "hfm_crypto";
input bool ScanAllBrokerSymbols = true;
input bool ScanMarketWatchSymbols = false;
input int MaxSymbolsToExport = 200;
input int MaxBrokerSymbolSamples = 160;
input bool ExportCopyRatesHistory = true;
input ENUM_TIMEFRAMES RatesTimeframe = PERIOD_M15;
input int RatesLookbackDays = 60;
input int MaxRateBarsPerSymbol = 1500;

const string OUTPUT_FILE_NAME = "QuantGod_HFMCryptoSymbolSpecs.json";
const string RATES_OUTPUT_FILE_NAME = "QuantGod_HFMCryptoRatesExport.json";

// Standalone HFM Crypto Spec Exporter BEGIN
string JsonEscape(string value)
{
   string out = "";
   for(int i = 0; i < StringLen(value); i++)
   {
      ushort ch = StringGetCharacter(value, i);
      if(ch == 34) out += "\\\"";
      else if(ch == 92) out += "\\\\";
      else if(ch == 8) out += "\\b";
      else if(ch == 12) out += "\\f";
      else if(ch == 10) out += "\\n";
      else if(ch == 13) out += "\\r";
      else if(ch == 9) out += "\\t";
      else if(ch < 32) out += StringFormat("\\u%04X", ch);
      else out += ShortToString(ch);
   }
   return out;
}

string JsonString(string value)
{
   return "\"" + JsonEscape(value) + "\"";
}

string JsonBool(bool value)
{
   return value ? "true" : "false";
}

string JsonDouble(double value, int digits = 10)
{
   return DoubleToString(value, digits);
}

string GetSymbolStringValue(string symbol, ENUM_SYMBOL_INFO_STRING property)
{
   string value = "";
   ResetLastError();
   SymbolInfoString(symbol, property, value);
   return value;
}

long GetSymbolIntegerValue(string symbol, ENUM_SYMBOL_INFO_INTEGER property)
{
   long value = 0;
   ResetLastError();
   SymbolInfoInteger(symbol, property, value);
   return value;
}

double GetSymbolDoubleValue(string symbol, ENUM_SYMBOL_INFO_DOUBLE property)
{
   double value = 0.0;
   ResetLastError();
   SymbolInfoDouble(symbol, property, value);
   return value;
}

string NormalizeHfmCryptoCanonical(string brokerSymbol)
{
   string value = brokerSymbol;
   if(StringLen(value) > 0 && StringSubstr(value, 0, 1) == "#")
      value = StringSubstr(value, 1);

   int len = StringLen(value);
   if(len > 4)
   {
      string last = StringSubstr(value, len - 1, 1);
      string withoutLast = StringSubstr(value, 0, len - 1);
      int coreLen = StringLen(withoutLast);
      if((last == "r" || last == "x" || last == "c") && coreLen >= 3 && StringSubstr(withoutLast, coreLen - 3, 3) == "USD")
         value = withoutLast;
   }
   return value;
}

bool LooksLikeHfmCryptoSymbol(string brokerSymbol)
{
   string canonical = NormalizeHfmCryptoCanonical(brokerSymbol);
   string canonicalList =
      "|AAVEUSD|ADAUSD|ALGOUSD|APTUSD|ATOMUSD|AVAXUSD|BCHUSD|BNBUSD|BTCUSD|CRVUSD|"
      "DOGEUSD|DOTUSD|ETCUSD|ETHUSD|FETUSD|FILUSD|FLOWUSD|GALAUSD|GRTUSD|HBARUSD|"
      "ICPUSD|IMXUSD|IOTAUSD|LINKUSD|LTCUSD|NEARUSD|SANDUSD|SHIBUSD|SOLUSD|THETAUSD|"
      "TRXUSD|UNIUSD|XLMUSD|XRPUSD|XTZUSD|";
   if(StringFind(canonicalList, "|" + canonical + "|") >= 0)
      return true;

   string description = GetSymbolStringValue(brokerSymbol, SYMBOL_DESCRIPTION);
   string path = GetSymbolStringValue(brokerSymbol, SYMBOL_PATH);
   bool cryptoPath = StringFind(path, "Crypto") >= 0 || StringFind(path, "crypto") >= 0;
   bool cryptoDescription = StringFind(description, "Crypto") >= 0 || StringFind(description, "crypto") >= 0;
   return (cryptoPath || cryptoDescription) && StringFind(canonical, "USD") >= 0;
}

bool AlreadyVisited(string visited, string symbol)
{
   return StringFind(visited, "|" + symbol + "|") >= 0;
}

bool AppendSymbolSpecsJson(string symbol, string &json, int &count)
{
   if(StringLen(symbol) == 0)
      return false;

   long exists = GetSymbolIntegerValue(symbol, SYMBOL_EXIST);
   string description = GetSymbolStringValue(symbol, SYMBOL_DESCRIPTION);
   string path = GetSymbolStringValue(symbol, SYMBOL_PATH);
   string base = GetSymbolStringValue(symbol, SYMBOL_CURRENCY_BASE);
   string profit = GetSymbolStringValue(symbol, SYMBOL_CURRENCY_PROFIT);

   MqlTick tick;
   bool tickOk = SymbolInfoTick(symbol, tick);
   if(exists == 0 && description == "" && path == "" && !tickOk)
      return false;

   if(count > 0)
      json += ",\n";

   long visible = GetSymbolIntegerValue(symbol, SYMBOL_VISIBLE);
   long selected = GetSymbolIntegerValue(symbol, SYMBOL_SELECT);
   long digits = GetSymbolIntegerValue(symbol, SYMBOL_DIGITS);
   long spread = GetSymbolIntegerValue(symbol, SYMBOL_SPREAD);
   long spreadFloat = GetSymbolIntegerValue(symbol, SYMBOL_SPREAD_FLOAT);
   long tradeMode = GetSymbolIntegerValue(symbol, SYMBOL_TRADE_MODE);
   long calcMode = GetSymbolIntegerValue(symbol, SYMBOL_TRADE_CALC_MODE);
   double point = GetSymbolDoubleValue(symbol, SYMBOL_POINT);
   double contractSize = GetSymbolDoubleValue(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   double tickSize = GetSymbolDoubleValue(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = GetSymbolDoubleValue(symbol, SYMBOL_TRADE_TICK_VALUE);
   double volumeMin = GetSymbolDoubleValue(symbol, SYMBOL_VOLUME_MIN);
   double volumeMax = GetSymbolDoubleValue(symbol, SYMBOL_VOLUME_MAX);
   double volumeStep = GetSymbolDoubleValue(symbol, SYMBOL_VOLUME_STEP);
   double swapLong = GetSymbolDoubleValue(symbol, SYMBOL_SWAP_LONG);
   double swapShort = GetSymbolDoubleValue(symbol, SYMBOL_SWAP_SHORT);
   double marginInitial = GetSymbolDoubleValue(symbol, SYMBOL_MARGIN_INITIAL);

   json += "    {\n";
   json += "      \"brokerSymbol\": " + JsonString(symbol) + ",\n";
   json += "      \"canonicalSymbol\": " + JsonString(NormalizeHfmCryptoCanonical(symbol)) + ",\n";
   json += "      \"description\": " + JsonString(description) + ",\n";
   json += "      \"path\": " + JsonString(path) + ",\n";
   json += "      \"currencyBase\": " + JsonString(base) + ",\n";
   json += "      \"currencyProfit\": " + JsonString(profit) + ",\n";
   json += "      \"visible\": " + JsonBool(visible != 0) + ",\n";
   json += "      \"selected\": " + JsonBool(selected != 0) + ",\n";
   json += "      \"digits\": " + IntegerToString((int)digits) + ",\n";
   json += "      \"point\": " + JsonDouble(point) + ",\n";
   json += "      \"spread\": " + IntegerToString((int)spread) + ",\n";
   json += "      \"spreadFloat\": " + JsonBool(spreadFloat != 0) + ",\n";
   json += "      \"tradeMode\": " + IntegerToString((int)tradeMode) + ",\n";
   json += "      \"calcMode\": " + IntegerToString((int)calcMode) + ",\n";
   json += "      \"tradeContractSize\": " + JsonDouble(contractSize) + ",\n";
   json += "      \"tradeTickSize\": " + JsonDouble(tickSize) + ",\n";
   json += "      \"tradeTickValue\": " + JsonDouble(tickValue) + ",\n";
   json += "      \"volumeMin\": " + JsonDouble(volumeMin) + ",\n";
   json += "      \"volumeMax\": " + JsonDouble(volumeMax) + ",\n";
   json += "      \"volumeStep\": " + JsonDouble(volumeStep) + ",\n";
   json += "      \"swapLong\": " + JsonDouble(swapLong) + ",\n";
   json += "      \"swapShort\": " + JsonDouble(swapShort) + ",\n";
   json += "      \"marginInitial\": " + JsonDouble(marginInitial) + ",\n";
   json += "      \"tickOk\": " + JsonBool(tickOk) + ",\n";
   json += "      \"bid\": " + JsonDouble(tickOk ? tick.bid : 0.0) + ",\n";
   json += "      \"ask\": " + JsonDouble(tickOk ? tick.ask : 0.0) + ",\n";
   json += "      \"tradeEnabled\": " + JsonBool(tradeMode > 0) + "\n";
   json += "    }";
   count++;
   return true;
}

void AppendBrokerSymbolSampleJson(string symbol, string &json, int &count)
{
   if(count > 0)
      json += ",\n";

   long visible = GetSymbolIntegerValue(symbol, SYMBOL_VISIBLE);
   long selected = GetSymbolIntegerValue(symbol, SYMBOL_SELECT);
   long digits = GetSymbolIntegerValue(symbol, SYMBOL_DIGITS);
   long spread = GetSymbolIntegerValue(symbol, SYMBOL_SPREAD);
   long tradeMode = GetSymbolIntegerValue(symbol, SYMBOL_TRADE_MODE);
   long calcMode = GetSymbolIntegerValue(symbol, SYMBOL_TRADE_CALC_MODE);
   double point = GetSymbolDoubleValue(symbol, SYMBOL_POINT);

   json += "    {\n";
   json += "      \"brokerSymbol\": " + JsonString(symbol) + ",\n";
   json += "      \"canonicalSymbol\": " + JsonString(NormalizeHfmCryptoCanonical(symbol)) + ",\n";
   json += "      \"description\": " + JsonString(GetSymbolStringValue(symbol, SYMBOL_DESCRIPTION)) + ",\n";
   json += "      \"path\": " + JsonString(GetSymbolStringValue(symbol, SYMBOL_PATH)) + ",\n";
   json += "      \"currencyBase\": " + JsonString(GetSymbolStringValue(symbol, SYMBOL_CURRENCY_BASE)) + ",\n";
   json += "      \"currencyProfit\": " + JsonString(GetSymbolStringValue(symbol, SYMBOL_CURRENCY_PROFIT)) + ",\n";
   json += "      \"visible\": " + JsonBool(visible != 0) + ",\n";
   json += "      \"selected\": " + JsonBool(selected != 0) + ",\n";
   json += "      \"digits\": " + IntegerToString((int)digits) + ",\n";
   json += "      \"point\": " + JsonDouble(point) + ",\n";
   json += "      \"spread\": " + IntegerToString((int)spread) + ",\n";
   json += "      \"tradeMode\": " + IntegerToString((int)tradeMode) + ",\n";
   json += "      \"calcMode\": " + IntegerToString((int)calcMode) + ",\n";
   json += "      \"looksLikeCrypto\": " + JsonBool(LooksLikeHfmCryptoSymbol(symbol)) + "\n";
   json += "    }";
   count++;
}

string BuildBrokerSymbolSamplesJson(bool selectedOnly, int maxSamples, int &total, int &sampleCount, int &cryptoLikeCount)
{
   total = SymbolsTotal(selectedOnly);
   sampleCount = 0;
   cryptoLikeCount = 0;
   string json = "";

   for(int i = 0; i < total; i++)
   {
      string symbol = SymbolName(i, selectedOnly);
      if(LooksLikeHfmCryptoSymbol(symbol))
         cryptoLikeCount++;
      if(sampleCount < maxSamples)
         AppendBrokerSymbolSampleJson(symbol, json, sampleCount);
   }

   return json;
}

string BuildStandaloneHfmCryptoSymbolSpecsJson()
{
   string candidates[] = {
      "#AAVEUSD", "#ADAUSD", "#ALGOUSD", "#APTUSD", "#ATOMUSD", "#AVAXUSD", "#BCHUSD", "#BNBUSD", "#BTCUSD",
      "#CRVUSD", "#DOGEUSD", "#DOTUSD", "#ETCUSD", "#ETHUSD", "#FETUSD", "#FILUSD", "#FLOWUSD", "#GALAUSD",
      "#GRTUSD", "#HBARUSD", "#ICPUSD", "#IMXUSD", "#IOTAUSD", "#LINKUSD", "#LTCUSD", "#NEARUSD", "#SANDUSD",
      "#SHIBUSD", "#SOLUSD", "#THETAUSD", "#TRXUSD", "#UNIUSD", "#XLMUSD", "#XRPUSD", "#XTZUSD",
      "#AAVEUSDr", "#ADAUSDr", "#ALGOUSDr", "#APTUSDr", "#ATOMUSDr", "#AVAXUSDr", "#BCHUSDr", "#BNBUSDr", "#BTCUSDr",
      "#CRVUSDr", "#DOGEUSDr", "#DOTUSDr", "#ETCUSDr", "#ETHUSDr", "#FETUSDr", "#FILUSDr", "#FLOWUSDr", "#GALAUSDr",
      "#GRTUSDr", "#HBARUSDr", "#ICPUSDr", "#IMXUSDr", "#IOTAUSDr", "#LINKUSDr", "#LTCUSDr", "#NEARUSDr", "#SANDUSDr",
      "#SHIBUSDr", "#SOLUSDr", "#THETAUSDr", "#TRXUSDr", "#UNIUSDr", "#XLMUSDr", "#XRPUSDr", "#XTZUSDr",
      "#BTCUSDx", "#ETHUSDx", "#XRPUSDx",
      "AAVEUSD", "ADAUSD", "ALGOUSD", "APTUSD", "ATOMUSD", "AVAXUSD", "BCHUSD", "BNBUSD", "BTCUSD",
      "CRVUSD", "DOGEUSD", "DOTUSD", "ETCUSD", "ETHUSD", "FETUSD", "FILUSD", "FLOWUSD", "GALAUSD",
      "GRTUSD", "HBARUSD", "ICPUSD", "IMXUSD", "IOTAUSD", "LINKUSD", "LTCUSD", "NEARUSD", "SANDUSD",
      "SHIBUSD", "SOLUSD", "THETAUSD", "TRXUSD", "UNIUSD", "XLMUSD", "XRPUSD", "XTZUSD"
   };

   string symbolsJson = "";
   string visited = "|";
   int count = 0;
   int scanned = 0;

   for(int i = 0; i < ArraySize(candidates) && count < MaxSymbolsToExport; i++)
   {
      string symbol = candidates[i];
      if(AlreadyVisited(visited, symbol))
         continue;
      visited += symbol + "|";
      scanned++;
      AppendSymbolSpecsJson(symbol, symbolsJson, count);
   }

   if(ScanAllBrokerSymbols)
   {
      int total = SymbolsTotal(false);
      for(int i = 0; i < total && count < MaxSymbolsToExport; i++)
      {
         string symbol = SymbolName(i, false);
         if(!LooksLikeHfmCryptoSymbol(symbol) || AlreadyVisited(visited, symbol))
            continue;
         visited += symbol + "|";
         scanned++;
         AppendSymbolSpecsJson(symbol, symbolsJson, count);
      }
   }

   if(ScanMarketWatchSymbols)
   {
      int total = SymbolsTotal(true);
      for(int i = 0; i < total && count < MaxSymbolsToExport; i++)
      {
         string symbol = SymbolName(i, true);
         if(!LooksLikeHfmCryptoSymbol(symbol) || AlreadyVisited(visited, symbol))
            continue;
         visited += symbol + "|";
         scanned++;
         AppendSymbolSpecsJson(symbol, symbolsJson, count);
      }
   }

   int brokerTotalAll = 0;
   int brokerSampleCount = 0;
   int brokerCryptoLikeCount = 0;
   string brokerSamplesJson = BuildBrokerSymbolSamplesJson(false, MaxBrokerSymbolSamples, brokerTotalAll, brokerSampleCount, brokerCryptoLikeCount);

   int marketWatchTotal = 0;
   int marketWatchSampleCount = 0;
   int marketWatchCryptoLikeCount = 0;
   string marketWatchSamplesJson = BuildBrokerSymbolSamplesJson(true, MaxBrokerSymbolSamples, marketWatchTotal, marketWatchSampleCount, marketWatchCryptoLikeCount);

   string json = "{\n";
   json += "  \"schema\": \"quantgod.mql5.hfm_crypto_symbol_specs.v1\",\n";
   json += "  \"source\": \"MQL5_SYMBOLINFO_READONLY_STANDALONE\",\n";
   json += "  \"script\": \"QuantGod_HFMCryptoSpecExporter.mq5\",\n";
   json += "  \"enabled\": true,\n";
   json += "  \"exportFolder\": " + JsonString(ExportFolderName) + ",\n";
   json += "  \"scanAllBrokerSymbols\": " + JsonBool(ScanAllBrokerSymbols) + ",\n";
   json += "  \"candidateSymbolsScanned\": " + IntegerToString(scanned) + ",\n";
   json += "  \"brokerSymbolTotalAll\": " + IntegerToString(brokerTotalAll) + ",\n";
   json += "  \"brokerSymbolTotalMarketWatch\": " + IntegerToString(marketWatchTotal) + ",\n";
   json += "  \"brokerCryptoLikeCountAll\": " + IntegerToString(brokerCryptoLikeCount) + ",\n";
   json += "  \"brokerCryptoLikeCountMarketWatch\": " + IntegerToString(marketWatchCryptoLikeCount) + ",\n";
   json += "  \"brokerSymbolSampleCount\": " + IntegerToString(brokerSampleCount) + ",\n";
   json += "  \"symbolCount\": " + IntegerToString(count) + ",\n";
   json += "  \"symbols\": [\n";
   json += symbolsJson;
   json += "\n  ],\n";
   json += "  \"brokerSymbolSamples\": [\n";
   json += brokerSamplesJson;
   json += "\n  ],\n";
   json += "  \"marketWatchSymbolSampleCount\": " + IntegerToString(marketWatchSampleCount) + ",\n";
   json += "  \"marketWatchSymbolSamples\": [\n";
   json += marketWatchSamplesJson;
   json += "\n  ],\n";
   json += "  \"safety\": {\n";
   json += "    \"readOnly\": true,\n";
   json += "    \"orderSendAllowed\": false,\n";
   json += "    \"mt5OrderSendAllowed\": false,\n";
   json += "    \"writesMt5OrderRequest\": false,\n";
   json += "    \"symbolSelectAllowed\": false,\n";
   json += "    \"livePresetMutationAllowed\": false\n";
   json += "  }\n";
   json += "}\n";
   return json;
}

string RateTimeframeLabel(ENUM_TIMEFRAMES timeframe)
{
   if(timeframe == PERIOD_M1) return "M1";
   if(timeframe == PERIOD_M5) return "M5";
   if(timeframe == PERIOD_M15) return "M15";
   if(timeframe == PERIOD_M30) return "M30";
   if(timeframe == PERIOD_H1) return "H1";
   if(timeframe == PERIOD_H4) return "H4";
   if(timeframe == PERIOD_D1) return "D1";
   return IntegerToString((int)timeframe);
}

string SafeFileToken(string value)
{
   string out = "";
   for(int i = 0; i < StringLen(value); i++)
   {
      ushort ch = StringGetCharacter(value, i);
      if((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9'))
         out += ShortToString(ch);
      else
         out += "_";
   }
   return out;
}

bool SymbolExistsForRates(string symbol)
{
   long exists = GetSymbolIntegerValue(symbol, SYMBOL_EXIST);
   string description = GetSymbolStringValue(symbol, SYMBOL_DESCRIPTION);
   string path = GetSymbolStringValue(symbol, SYMBOL_PATH);
   MqlTick tick;
   bool tickOk = SymbolInfoTick(symbol, tick);
   return exists != 0 || description != "" || path != "" || tickOk;
}

int ExportRatesForSymbol(string symbol, string &jsonItems, int &seriesCount)
{
   if(!SymbolExistsForRates(symbol))
      return 0;

   datetime now = TimeCurrent();
   if(now <= 0)
      now = TimeLocal();
   int lookbackDays = MathMax(1, RatesLookbackDays);
   int maxBars = MathMax(50, MaxRateBarsPerSymbol);
   datetime fromTime = now - lookbackDays * 24 * 60 * 60;
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   ResetLastError();
   int copied = CopyRates(symbol, RatesTimeframe, fromTime, now, rates);

   string canonical = NormalizeHfmCryptoCanonical(symbol);
   string timeframeLabel = RateTimeframeLabel(RatesTimeframe);
   string csvPath = ExportFolderName + "\\rates\\" + SafeFileToken(canonical) + "__" + SafeFileToken(symbol) + "__" + timeframeLabel + ".csv";
   int rows = 0;
   int digits = (int)GetSymbolIntegerValue(symbol, SYMBOL_DIGITS);
   if(digits <= 0)
      digits = 5;

   if(copied > 0)
   {
      int start = MathMax(0, copied - maxBars);
      int handle = FileOpen(csvPath, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE, ',', CP_UTF8);
      if(handle != INVALID_HANDLE)
      {
         FileWrite(handle, "epoch", "timestamp", "open", "high", "low", "close", "tick_volume", "spread", "real_volume");
         for(int i = start; i < copied; i++)
         {
            FileWrite(handle,
                      IntegerToString((long)rates[i].time),
                      TimeToString(rates[i].time, TIME_DATE | TIME_SECONDS),
                      DoubleToString(rates[i].open, digits),
                      DoubleToString(rates[i].high, digits),
                      DoubleToString(rates[i].low, digits),
                      DoubleToString(rates[i].close, digits),
                      IntegerToString((long)rates[i].tick_volume),
                      IntegerToString((long)rates[i].spread),
                      IntegerToString((long)rates[i].real_volume));
            rows++;
         }
         FileFlush(handle);
         FileClose(handle);
      }
   }

   if(seriesCount > 0)
      jsonItems += ",\n";
   jsonItems += "    {\n";
   jsonItems += "      \"brokerSymbol\": " + JsonString(symbol) + ",\n";
   jsonItems += "      \"canonicalSymbol\": " + JsonString(canonical) + ",\n";
   jsonItems += "      \"timeframe\": " + JsonString(timeframeLabel) + ",\n";
   jsonItems += "      \"file\": " + JsonString(csvPath) + ",\n";
   jsonItems += "      \"copiedBars\": " + IntegerToString(rows) + ",\n";
   jsonItems += "      \"copyRatesReturned\": " + IntegerToString(copied) + ",\n";
   jsonItems += "      \"ok\": " + JsonBool(rows > 0) + ",\n";
   jsonItems += "      \"error\": " + JsonString(rows > 0 ? "" : "CopyRates returned no rows or CSV open failed") + "\n";
   jsonItems += "    }";
   seriesCount++;
   return rows;
}

void AppendRatesCandidate(string symbol, string &visited, string &items, int &seriesCount, int &scanned, int &totalRows)
{
   if(AlreadyVisited(visited, symbol))
      return;
   visited += symbol + "|";
   scanned++;
   if(!LooksLikeHfmCryptoSymbol(symbol))
      return;
   totalRows += ExportRatesForSymbol(symbol, items, seriesCount);
}

void ExportStandaloneHfmCryptoRates()
{
   if(!ExportCopyRatesHistory)
      return;

   FolderCreate(ExportFolderName);
   FolderCreate(ExportFolderName + "\\rates");
   string candidates[] = {
      "#BTCUSD", "#ETHUSD", "#SOLUSD", "#XRPUSD", "#DOGEUSD", "#LTCUSD",
      "#BTCUSDr", "#ETHUSDr", "#SOLUSDr", "#XRPUSDr", "#DOGEUSDr", "#LTCUSDr",
      "#BTCUSDx", "#ETHUSDx", "#XRPUSDx",
      "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "DOGEUSD", "LTCUSD"
   };
   string visited = "|";
   string items = "";
   int seriesCount = 0;
   int scanned = 0;
   int totalRows = 0;

   for(int i = 0; i < ArraySize(candidates) && seriesCount < MaxSymbolsToExport; i++)
      AppendRatesCandidate(candidates[i], visited, items, seriesCount, scanned, totalRows);

   if(ScanAllBrokerSymbols)
   {
      int total = SymbolsTotal(false);
      for(int i = 0; i < total && seriesCount < MaxSymbolsToExport; i++)
         AppendRatesCandidate(SymbolName(i, false), visited, items, seriesCount, scanned, totalRows);
   }

   if(ScanMarketWatchSymbols)
   {
      int total = SymbolsTotal(true);
      for(int i = 0; i < total && seriesCount < MaxSymbolsToExport; i++)
         AppendRatesCandidate(SymbolName(i, true), visited, items, seriesCount, scanned, totalRows);
   }

   string payload = "{\n";
   payload += "  \"schema\": \"quantgod.mql5.hfm_crypto_rates_export.v1\",\n";
   payload += "  \"source\": \"MQL5_COPYRATES_READONLY_STANDALONE\",\n";
   payload += "  \"script\": \"QuantGod_HFMCryptoSpecExporter.mq5\",\n";
   payload += "  \"timeframe\": " + JsonString(RateTimeframeLabel(RatesTimeframe)) + ",\n";
   payload += "  \"lookbackDays\": " + IntegerToString(MathMax(1, RatesLookbackDays)) + ",\n";
   payload += "  \"maxBarsPerSymbol\": " + IntegerToString(MathMax(50, MaxRateBarsPerSymbol)) + ",\n";
   payload += "  \"candidateSymbolsScanned\": " + IntegerToString(scanned) + ",\n";
   payload += "  \"seriesCount\": " + IntegerToString(seriesCount) + ",\n";
   payload += "  \"totalBars\": " + IntegerToString(totalRows) + ",\n";
   payload += "  \"symbols\": [\n" + items + "\n  ],\n";
   payload += "  \"safety\": {\"readOnly\": true, \"orderSendAllowed\": false, \"mt5OrderSendAllowed\": false, \"writesMt5OrderRequest\": false, \"symbolSelectAllowed\": false, \"livePresetMutationAllowed\": false}\n";
   payload += "}\n";

   string manifestPath = ExportFolderName + "\\" + RATES_OUTPUT_FILE_NAME;
   int handle = FileOpen(manifestPath, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      Print("QuantGod standalone HFM crypto rates export failed: ", manifestPath, " error=", GetLastError());
      return;
   }
   FileWriteString(handle, payload);
   FileClose(handle);
   Print("QuantGod standalone HFM crypto rates exported: ", manifestPath, " rows=", totalRows);
}
// Standalone HFM Crypto Spec Exporter END

void OnStart()
{
   FolderCreate(ExportFolderName);
   string relativePath = ExportFolderName + "\\" + OUTPUT_FILE_NAME;
   string payload = BuildStandaloneHfmCryptoSymbolSpecsJson();
   ResetLastError();
   int handle = FileOpen(relativePath, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      Print("QuantGod standalone HFM crypto specs export failed: ", relativePath, " error=", GetLastError());
      return;
   }
   FileWriteString(handle, payload);
   FileClose(handle);
   Print("QuantGod standalone HFM crypto specs exported: ", relativePath);
   ExportStandaloneHfmCryptoRates();
}
