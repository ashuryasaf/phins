codeunit 50102 "PHINS Policy Management"
{
    /// <summary>
    /// Policy Management for PHINS Insurance
    /// Handles policy creation, renewal, and lifecycle management
    /// </summary>

    trigger OnRun()
    begin
        // Entry point for scheduled jobs
    end;

    procedure CreatePolicy(CustomerID: Code[20]; PolicyType: Integer; StartDate: Date; PremiumAmount: Decimal; CoverageAmount: Decimal; Deductible: Decimal): Code[20]
    var
        Policy: Record "PHINS Insurance Policy";
        PolicyIDCounter: Integer;
    begin
        PolicyIDCounter := GetNextPolicyID();
        Policy.Init();
        Policy."Policy ID" := 'POL' + Format(PolicyIDCounter);
        Policy."Customer ID" := CustomerID;
        Policy."Policy Type" := PolicyType;
        Policy."Start Date" := StartDate;
        Policy."End Date" := CalcDate('<+1Y>', StartDate);
        Policy."Premium Amount" := PremiumAmount;
        Policy."Coverage Amount" := CoverageAmount;
        Policy.Deductible := Deductible;
        Policy.Status := Policy.Status::Active;
        Policy."Underwriting Status" := Policy."Underwriting Status"::Pending;
        Policy."Payment Frequency" := Policy."Payment Frequency"::Annual;
        Policy.Insert(true);
        
        exit(Policy."Policy ID");
    end;

    procedure RenewPolicy(PolicyID: Code[20])
    var
        Policy: Record "PHINS Insurance Policy";
    begin
        if Policy.Get(PolicyID) then begin
            Policy."Start Date" := Policy."End Date" + 1;
            Policy."End Date" := CalcDate('<+1Y>', Policy."Start Date");
            Policy.Status := Policy.Status::Active;
            Policy."Underwriting Status" := Policy."Underwriting Status"::Pending;
            Policy.Modify();
        end;
    end;

    procedure CancelPolicy(PolicyID: Code[20]; Reason: Text[250])
    var
        Policy: Record "PHINS Insurance Policy";
    begin
        if Policy.Get(PolicyID) then begin
            Policy.Status := Policy.Status::Cancelled;
            Policy.Notes := Reason;
            Policy.Modify();
        end;
    end;

    procedure SuspendPolicy(PolicyID: Code[20])
    var
        Policy: Record "PHINS Insurance Policy";
    begin
        if Policy.Get(PolicyID) then begin
            Policy.Status := Policy.Status::Suspended;
            Policy.Modify();
        end;
    end;

    procedure ReactivatePolicy(PolicyID: Code[20])
    var
        Policy: Record "PHINS Insurance Policy";
    begin
        if Policy.Get(PolicyID) then begin
            if Policy.Status = Policy.Status::Suspended then begin
                Policy.Status := Policy.Status::Active;
                Policy.Modify();
            end;
        end;
    end;

    procedure GetPolicyStatus(PolicyID: Code[20]): Text
    var
        Policy: Record "PHINS Insurance Policy";
    begin
        if Policy.Get(PolicyID) then
            exit(Format(Policy.Status))
        else
            exit('Not Found');
    end;

    local procedure GetNextPolicyID(): Integer
    var
        Policy: Record "PHINS Insurance Policy";
    begin
        if Policy.FindLast() then
            exit(StrToInt(CopyStr(Policy."Policy ID", 4)) + 1)
        else
            exit(1);
    end;
}
