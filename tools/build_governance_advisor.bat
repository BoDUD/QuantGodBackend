@echo off
setlocal
set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "RUNTIME_DIR=%~1"
if "%RUNTIME_DIR%"=="" set "RUNTIME_DIR=C:\Program Files\HFM Metatrader 5\MQL5\Files"
set "TESTER_ROOT=%REPO_ROOT%\runtime\HFM_MT5_Tester_Isolated"

python "%REPO_ROOT%\tools\build_param_optimization_plan.py" --runtime-dir "%RUNTIME_DIR%"
python "%REPO_ROOT%\tools\watch_param_lab_reports.py" --runtime-dir "%RUNTIME_DIR%"
python "%REPO_ROOT%\tools\build_governance_advisor.py" --runtime-dir "%RUNTIME_DIR%"
python "%REPO_ROOT%\tools\build_strategy_version_registry.py" --runtime-dir "%RUNTIME_DIR%"
python "%REPO_ROOT%\tools\build_optimizer_v2_plan.py" --runtime-dir "%RUNTIME_DIR%"
python "%REPO_ROOT%\tools\build_version_promotion_gate.py" --runtime-dir "%RUNTIME_DIR%"
python "%REPO_ROOT%\tools\build_param_lab_auto_scheduler.py" --runtime-dir "%RUNTIME_DIR%"
python "%REPO_ROOT%\tools\build_param_lab_run_recovery.py" --runtime-dir "%RUNTIME_DIR%"
python "%REPO_ROOT%\tools\run_param_lab_auto_tester_window.py" --runtime-dir "%RUNTIME_DIR%" --tester-root "%TESTER_ROOT%" --require-isolated-tester
python "%REPO_ROOT%\tools\build_param_lab_run_recovery.py" --runtime-dir "%RUNTIME_DIR%"
python "%REPO_ROOT%\tools\build_governance_advisor.py" --runtime-dir "%RUNTIME_DIR%"
endlocal
