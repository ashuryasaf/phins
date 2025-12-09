codeunit 50103 "PHINS Underwriting Engine"
{
    /// <summary>
    /// Underwriting Management for PHINS Insurance
    /// Handles risk assessment, underwriting decisions, and policy approval
    /// </summary>

    trigger OnRun()
    begin
        // Entry point for scheduled jobs
    end;

    procedure InitiateUnderwriting(PolicyID: Code[20]; CustomerID: Code[20]): Code[20]
    var
        Underwriting: Record "PHINS Underwriting";
        UnderwritingIDCounter: Integer;
    begin
        UnderwritingIDCounter := GetNextUnderwritingID();
        Underwriting.Init();
        Underwriting."Underwriting ID" := 'UW' + Format(UnderwritingIDCounter);
        Underwriting."Policy ID" := PolicyID;
        Underwriting."Customer ID" := CustomerID;
        Underwriting."Submission Date" := Today();
        Underwriting.Decision := Underwriting.Decision::Pending;
        Underwriting."Risk Assessment" := Underwriting."Risk Assessment"::Medium;
        Underwriting.Insert(true);
        
        exit(Underwriting."Underwriting ID");
    end;

    procedure AssessRisk(UnderwritingID: Code[20]; RiskLevel: Integer; MedicalRequired: Boolean; AdditionalDocs: Boolean)
    var
        Underwriting: Record "PHINS Underwriting";
    begin
        if Underwriting.Get(UnderwritingID) then begin
            Underwriting."Risk Assessment" := RiskLevel;
            Underwriting."Medical Required" := MedicalRequired;
            Underwriting."Additional Documents Required" := AdditionalDocs;
            Underwriting.Modify();
        end;
    end;

    procedure ApproveUnderwriting(UnderwritingID: Code[20]; PremiumAdjustment: Decimal): Boolean
    var
        Underwriting: Record "PHINS Underwriting";
    begin
        if Underwriting.Get(UnderwritingID) then begin
            Underwriting.Decision := Underwriting.Decision::Approved;
            Underwriting."Review Date" := Today();
            Underwriting."Premium Adjustment" := PremiumAdjustment;
            Underwriting.Modify();
            exit(true);
        end;
        exit(false);
    end;

    procedure RejectUnderwriting(UnderwritingID: Code[20]; Reason: Text[250])
    var
        Underwriting: Record "PHINS Underwriting";
    begin
        if Underwriting.Get(UnderwritingID) then begin
            Underwriting.Decision := Underwriting.Decision::Rejected;
            Underwriting."Review Date" := Today();
            Underwriting.Comments := Reason;
            Underwriting.Modify();
        end;
    end;

    procedure RequestAdditionalInfo(UnderwritingID: Code[20]; InfoRequired: Text[500])
    var
        Underwriting: Record "PHINS Underwriting";
    begin
        if Underwriting.Get(UnderwritingID) then begin
            Underwriting.Decision := Underwriting.Decision::Referred;
            Underwriting.Comments := InfoRequired;
            Underwriting."Additional Documents Required" := true;
            Underwriting.Modify();
        end;
    end;

    procedure GetUnderwritingStatus(UnderwritingID: Code[20]): Text
    var
        Underwriting: Record "PHINS Underwriting";
    begin
        if Underwriting.Get(UnderwritingID) then
            exit(Format(Underwriting.Decision))
        else
            exit('Not Found');
    end;

    local procedure GetNextUnderwritingID(): Integer
    var
        Underwriting: Record "PHINS Underwriting";
    begin
        if Underwriting.FindLast() then
            exit(StrToInt(CopyStr(Underwriting."Underwriting ID", 3)) + 1)
        else
            exit(1);
    end;
}
