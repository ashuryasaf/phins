codeunit 50104 "PHINS Accounting Management"
{
    /// <summary>
    /// Accounting Management for PHINS Insurance
    /// Handles premium allocation, risk/savings split, accounting ledger,
    /// and accumulative premium tracking for accounting books
    /// </summary>

    trigger OnRun()
    begin
        // Entry point for scheduled jobs
    end;

    #region Premium Allocation

    procedure AllocatePremium(BillID: Code[20]; PolicyID: Code[20]; CustomerID: Code[20]; 
                              TotalPremium: Decimal; RiskPercentage: Decimal): Code[20]
    var
        Allocation: Record "PHINS Premium Allocation";
        AllocationIDCounter: Integer;
        SavingsAmount: Decimal;
        RiskAmount: Decimal;
        SavingsPercentage: Decimal;
        Permissions = TableData "PHINS Premium Allocation" = RIMD, TableData "PHINS Accounting Ledger" = RIMD;
        // Add role-based permission checks in procedures as needed
    begin
        // Validate percentages
        if RiskPercentage < 0 or RiskPercentage > 100 then
            Error('Risk percentage must be between 0 and 100');
        
        SavingsPercentage := 100 - RiskPercentage;
        RiskAmount := TotalPremium * (RiskPercentage / 100);
        SavingsAmount := TotalPremium * (SavingsPercentage / 100);

        AllocationIDCounter := GetNextAllocationID();
        Allocation.Init();
        Allocation."Allocation ID" := 'ALLOC' + Format(AllocationIDCounter);
        Allocation."Bill ID" := BillID;
        Allocation."Policy ID" := PolicyID;
        Allocation."Customer ID" := CustomerID;
        Allocation."Allocation Date" := Today();
        Allocation."Total Premium" := TotalPremium;
        Allocation."Risk Premium" := RiskAmount;
        Allocation."Savings Premium" := SavingsAmount;
        Allocation."Risk Percentage" := RiskPercentage;
        Allocation."Savings Percentage" := SavingsPercentage;
        
        // Calculate investment ratio
        if SavingsAmount > 0 then
            Allocation."Investment Ratio" := RiskAmount / SavingsAmount
        else
            Allocation."Investment Ratio" := RiskAmount;
        
        Allocation.Status := Allocation.Status::Draft;
        Allocation.Insert(true);
        
        exit(Allocation."Allocation ID");
    end;

    procedure PostAllocation(AllocationID: Code[20])
    var
        Allocation: Record "PHINS Premium Allocation";
        LedgerEntry: Record "PHINS Accounting Ledger";
        EntryNo: Integer;
    begin
        if not Allocation.Get(AllocationID) then
            Error('Allocation %1 not found', AllocationID);
        
        if Allocation.Status = Allocation.Status::Posted then
            Error('Allocation %1 is already posted', AllocationID);

        // Create Risk Fund entry
        EntryNo := CreateLedgerEntry(
            AllocationID,
            Allocation."Policy ID",
            Allocation."Customer ID",
            Today(),
            'Risk Payment',
            'Risk Fund',
            Allocation."Risk Premium",
            0,
            'Risk Premium Posted - Premium: ' + Format(Allocation."Total Premium")
        );

        // Create Savings Fund entry
        EntryNo := CreateLedgerEntry(
            AllocationID,
            Allocation."Policy ID",
            Allocation."Customer ID",
            Today(),
            'Savings Deposit',
            'Savings Fund',
            Allocation."Savings Premium",
            0,
            'Savings Premium Posted - Premium: ' + Format(Allocation."Total Premium")
        );

        // Update allocation status
        Allocation.Status := Allocation.Status::Posted;
        Allocation."Posted Date" := Today();
        Allocation."Posted By" := UserId();
        Allocation.Modify();
    end;

    #endregion

    #region Ledger Operations

    procedure CreateLedgerEntry(AllocationID: Code[20]; PolicyID: Code[20]; CustomerID: Code[20]; 
                                EntryDate: Date; EntryType: Text; AccountType: Text;
                                DebitAmount: Decimal; CreditAmount: Decimal; Description: Text): Integer
    var
        LedgerEntry: Record "PHINS Accounting Ledger";
        NewEntryNo: Integer;
        RunningBalance: Decimal;
    begin
        // Get previous balance
        RunningBalance := GetAccountBalance(CustomerID, AccountType);
        
        // Update balance based on entry type
        if DebitAmount > 0 then
            RunningBalance += DebitAmount
        else if CreditAmount > 0 then
            RunningBalance -= CreditAmount;

        LedgerEntry.Init();
        NewEntryNo := LedgerEntry."Entry No." + 1;
        LedgerEntry."Entry No." := NewEntryNo;
        LedgerEntry."Allocation ID" := AllocationID;
        LedgerEntry."Policy ID" := PolicyID;
        LedgerEntry."Customer ID" := CustomerID;
        LedgerEntry."Entry Date" := EntryDate;
        LedgerEntry."Entry Type" := GetEntryTypeOption(EntryType);
        LedgerEntry."Account Type" := GetAccountTypeOption(AccountType);
        LedgerEntry."Debit Amount" := DebitAmount;
        LedgerEntry."Credit Amount" := CreditAmount;
        LedgerEntry.Balance := RunningBalance;
        LedgerEntry.Description := Description;
        LedgerEntry.Posted := true;
        LedgerEntry."Posted By" := UserId();
        LedgerEntry.Insert(true);
        
        exit(NewEntryNo);
    end;

    procedure GetAccountBalance(CustomerID: Code[20]; AccountType: Text): Decimal
    var
        LedgerEntry: Record "PHINS Accounting Ledger";
        Balance: Decimal;
    begin
        LedgerEntry.SetRange("Customer ID", CustomerID);
        LedgerEntry.SetRange("Account Type", GetAccountTypeOption(AccountType));
        LedgerEntry.SetCurrentKey("Entry No.");
        if LedgerEntry.FindLast() then
            Balance := LedgerEntry.Balance
        else
            Balance := 0;
        
        exit(Balance);
    end;

    #endregion

    #region Customer Reporting

    procedure GetCustomerPremiumSummary(CustomerID: Code[20]): Text
    var
        Allocation: Record "PHINS Premium Allocation";
        TotalPremium: Decimal;
        TotalRisk: Decimal;
        TotalSavings: Decimal;
    begin
        Allocation.SetRange("Customer ID", CustomerID);
        Allocation.SetRange(Status, Allocation.Status::Posted);
        
        if Allocation.FindSet() then begin
            repeat
                TotalPremium += Allocation."Total Premium";
                TotalRisk += Allocation."Risk Premium";
                TotalSavings += Allocation."Savings Premium";
            until Allocation.Next() = 0;
        end;
        
        exit(StrSubstNo(
            'Customer: %1 | Total Premium: %2 | Risk Coverage: %3 | Customer Savings: %4 | Ratio: %5:%6',
            CustomerID,
            Format(TotalPremium),
            Format(TotalRisk),
            Format(TotalSavings),
            GetRiskPercentage(TotalPremium, TotalRisk),
            GetSavingsPercentage(TotalPremium, TotalSavings)
        ));
    end;

    procedure GenerateCustomerStatement(CustomerID: Code[20]; StartDate: Date; EndDate: Date): Text
    var
        Allocation: Record "PHINS Premium Allocation";
        Statement: Text;
        MonthlyTotal: Decimal;
        MonthlyRisk: Decimal;
        MonthlySavings: Decimal;
    begin
        Statement := '====== CUSTOMER PREMIUM STATEMENT ======\n';
        Statement += 'Customer ID: ' + CustomerID + '\n';
        Statement += 'Period: ' + Format(StartDate) + ' to ' + Format(EndDate) + '\n';
        Statement += '========================================\n\n';

        Allocation.SetRange("Customer ID", CustomerID);
        Allocation.SetRange("Allocation Date", StartDate, EndDate);
        Allocation.SetRange(Status, Allocation.Status::Posted);
        
        if Allocation.FindSet() then begin
            repeat
                Statement += 'Date: ' + Format(Allocation."Allocation Date") + '\n';
                Statement += '  Total Premium: $' + Format(Allocation."Total Premium", 0, '<Sign><Integer><Decimals,2>') + '\n';
                Statement += '  - Risk Coverage (' + Format(Allocation."Risk Percentage") + '%): $' + 
                             Format(Allocation."Risk Premium", 0, '<Sign><Integer><Decimals,2>') + '\n';
                Statement += '  - Your Savings (' + Format(Allocation."Savings Percentage") + '%): $' + 
                             Format(Allocation."Savings Premium", 0, '<Sign><Integer><Decimals,2>') + '\n';
                Statement += '  Investment Ratio: ' + Format(Allocation."Investment Ratio", 0, '<Sign><Integer><Decimals,4>') + '\n\n';
                
                MonthlyTotal += Allocation."Total Premium";
                MonthlyRisk += Allocation."Risk Premium";
                MonthlySavings += Allocation."Savings Premium";
            until Allocation.Next() = 0;
        end;

        Statement += '========== PERIOD SUMMARY ==========\n';
        Statement += 'Total Premiums: $' + Format(MonthlyTotal, 0, '<Sign><Integer><Decimals,2>') + '\n';
        Statement += 'Total Risk Coverage: $' + Format(MonthlyRisk, 0, '<Sign><Integer><Decimals,2>') + '\n';
        Statement += 'Total Customer Savings: $' + Format(MonthlySavings, 0, '<Sign><Integer><Decimals,2>') + '\n';
        Statement += 'Average Risk %: ' + GetRiskPercentage(MonthlyTotal, MonthlyRisk) + '\n';
        Statement += 'Average Savings %: ' + GetSavingsPercentage(MonthlyTotal, MonthlySavings) + '\n';
        
        exit(Statement);
    end;

    #endregion

    #region Accounting Reports

    procedure GetAccumulativePremiumReport(PolicyID: Code[20]): Text
    var
        Allocation: Record "PHINS Premium Allocation";
        AccumPremium: Decimal;
        AccumRisk: Decimal;
        AccumSavings: Decimal;
        AllocationCount: Integer;
    begin
        Allocation.SetRange("Policy ID", PolicyID);
        Allocation.SetRange(Status, Allocation.Status::Posted);
        Allocation.SetCurrentKey("Allocation Date");
        
        if Allocation.FindSet() then begin
            repeat
                AccumPremium += Allocation."Total Premium";
                AccumRisk += Allocation."Risk Premium";
                AccumSavings += Allocation."Savings Premium";
                AllocationCount += 1;
            until Allocation.Next() = 0;
        end;
        
        exit(StrSubstNo(
            'Policy: %1 | Cumulative Premium: %2 | Total Risk: %3 | Total Savings: %4 | Allocations: %5',
            PolicyID,
            Format(AccumPremium),
            Format(AccumRisk),
            Format(AccumSavings),
            Format(AllocationCount)
        ));
    end;

    procedure GetRiskInvestmentRatio(CustomerID: Code[20]): Decimal
    var
        Allocation: Record "PHINS Premium Allocation";
        TotalRisk: Decimal;
        TotalSavings: Decimal;
    begin
        Allocation.SetRange("Customer ID", CustomerID);
        Allocation.SetRange(Status, Allocation.Status::Posted);
        
        if Allocation.FindSet() then begin
            repeat
                TotalRisk += Allocation."Risk Premium";
                TotalSavings += Allocation."Savings Premium";
            until Allocation.Next() = 0;
        end;
        
        if TotalSavings > 0 then
            exit(TotalRisk / TotalSavings)
        else
            exit(TotalRisk);
    end;

    procedure GenerateAccountingBook(StartDate: Date; EndDate: Date): Text
    var
        LedgerEntry: Record "PHINS Accounting Ledger";
        Report: Text;
        RiskFundBalance: Decimal;
        SavingsFundBalance: Decimal;
        ReinsuranceBalance: Decimal;
        TotalDebits: Decimal;
        TotalCredits: Decimal;
    begin
        Report := '====== ACCOUNTING BOOK - GENERAL LEDGER ======\n';
        Report += 'Period: ' + Format(StartDate) + ' to ' + Format(EndDate) + '\n';
        Report += '==============================================\n\n';

        LedgerEntry.SetRange("Entry Date", StartDate, EndDate);
        LedgerEntry.SetCurrentKey("Entry Date", "Entry Type");
        
        if LedgerEntry.FindSet() then begin
            repeat
                Report += Format(LedgerEntry."Entry Date") + ' | ';
                Report += LedgerEntry.Description + ' | ';
                Report += 'Debit: $' + Format(LedgerEntry."Debit Amount", 0, '<Sign><Integer><Decimals,2>') + ' | ';
                Report += 'Credit: $' + Format(LedgerEntry."Credit Amount", 0, '<Sign><Integer><Decimals,2>') + ' | ';
                Report += 'Balance: $' + Format(LedgerEntry.Balance, 0, '<Sign><Integer><Decimals,2>') + '\n';
                
                TotalDebits += LedgerEntry."Debit Amount";
                TotalCredits += LedgerEntry."Credit Amount";
            until LedgerEntry.Next() = 0;
        end;

        Report += '\n====== ACCOUNT BALANCES ======\n';
        Report += 'Risk Fund: $' + Format(GetFundBalance('Risk Fund'), 0, '<Sign><Integer><Decimals,2>') + '\n';
        Report += 'Savings Fund: $' + Format(GetFundBalance('Savings Fund'), 0, '<Sign><Integer><Decimals,2>') + '\n';
        Report += 'Reinsurance: $' + Format(GetFundBalance('Reinsurance'), 0, '<Sign><Integer><Decimals,2>') + '\n';
        Report += '\n====== TOTALS ======\n';
        Report += 'Total Debits: $' + Format(TotalDebits, 0, '<Sign><Integer><Decimals,2>') + '\n';
        Report += 'Total Credits: $' + Format(TotalCredits, 0, '<Sign><Integer><Decimals,2>') + '\n';
        
        exit(Report);
    end;

    #endregion

    #region Helper Functions

    local procedure GetNextAllocationID(): Integer
    var
        Allocation: Record "PHINS Premium Allocation";
    begin
        if Allocation.FindLast() then
            exit(StrToInt(CopyStr(Allocation."Allocation ID", 6)) + 1)
        else
            exit(1);
    end;

    local procedure GetEntryTypeOption(EntryType: Text): Integer
    begin
        case EntryType of
            'Premium Posted':
                exit(0);
            'Risk Payment':
                exit(1);
            'Savings Deposit':
                exit(2);
            'Investment Income':
                exit(3);
            'Claim Payment':
                exit(4);
            'Fee Applied':
                exit(5);
            else
                Error('Unknown entry type: %1', EntryType);
        end;
    end;

    local procedure GetAccountTypeOption(AccountType: Text): Integer
    begin
        case AccountType of
            'Risk Fund':
                exit(0);
            'Savings Fund':
                exit(1);
            'Reinsurance':
                exit(2);
            'Operating':
                exit(3);
            else
                Error('Unknown account type: %1', AccountType);
        end;
    end;

    local procedure GetFundBalance(FundType: Text): Decimal
    var
        LedgerEntry: Record "PHINS Accounting Ledger";
        Balance: Decimal;
    begin
        LedgerEntry.SetRange("Account Type", GetAccountTypeOption(FundType));
        LedgerEntry.SetCurrentKey("Entry No.");
        if LedgerEntry.FindLast() then
            Balance := LedgerEntry.Balance
        else
            Balance := 0;
        
        exit(Balance);
    end;

    local procedure GetRiskPercentage(TotalPremium: Decimal; RiskAmount: Decimal): Text
    begin
        if TotalPremium = 0 then
            exit('0%');
        exit(Format(Round((RiskAmount / TotalPremium) * 100, 0.01)) + '%');
    end;

    local procedure GetSavingsPercentage(TotalPremium: Decimal; SavingsAmount: Decimal): Text
    begin
        if TotalPremium = 0 then
            exit('0%');
        exit(Format(Round((SavingsAmount / TotalPremium) * 100, 0.01)) + '%');
    end;

    #endregion
}
