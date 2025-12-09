codeunit 50100 "PHINS Claims Management"
{
    /// <summary>
    /// Claims Processing Management for PHINS Insurance
    /// Handles claim creation, approval, rejection, and payment processing
    /// </summary>

    trigger OnRun()
    begin
        // Entry point for scheduled jobs
    end;

    procedure CreateClaim(PolicyID: Code[20]; CustomerID: Code[20]; ClaimAmount: Decimal; Description: Text[500]): Code[20]
    var
        Claim: Record "PHINS Claims";
        ClaimIDCounter: Integer;
    begin
        ClaimIDCounter := GetNextClaimID();
        Claim.Init();
        Claim."Claim ID" := 'CLM' + Format(ClaimIDCounter);
        Claim."Policy ID" := PolicyID;
        Claim."Customer ID" := CustomerID;
        Claim."Claim Date" := Today();
        Claim."Claim Amount" := ClaimAmount;
        Claim.Description := Description;
        Claim.Status := Claim.Status::Pending;
        Claim.Priority := Claim.Priority::Medium;
        Claim.Insert(true);
        
        exit(Claim."Claim ID");
    end;

    procedure ApproveClaim(ClaimID: Code[20]; ApprovedAmount: Decimal)
    var
        Claim: Record "PHINS Claims";
    begin
        if Claim.Get(ClaimID) then begin
            Claim.Status := Claim.Status::Approved;
            Claim."Approved Amount" := ApprovedAmount;
            Claim.Modify();
        end;
    end;

    procedure RejectClaim(ClaimID: Code[20]; Reason: Text[250])
    var
        Claim: Record "PHINS Claims";
    begin
        if Claim.Get(ClaimID) then begin
            Claim.Status := Claim.Status::Rejected;
            Claim.Notes := Reason;
            Claim.Modify();
        end;
    end;

    procedure ProcessClaimPayment(ClaimID: Code[20]): Boolean
    var
        Claim: Record "PHINS Claims";
    begin
        if Claim.Get(ClaimID) then begin
            if (Claim.Status = Claim.Status::Approved) and (Claim."Approved Amount" > 0) then begin
                Claim.Status := Claim.Status::Paid;
                Claim."Payment Date" := Today();
                Claim.Modify();
                exit(true);
            end;
        end;
        exit(false);
    end;

    local procedure GetNextClaimID(): Integer
    var
        Claim: Record "PHINS Claims";
    begin
        if Claim.FindLast() then
            exit(StrToInt(CopyStr(Claim."Claim ID", 4)) + 1)
        else
            exit(1);
    end;

    procedure GetClaimStatus(ClaimID: Code[20]): Text
    var
        Claim: Record "PHINS Claims";
    begin
        if Claim.Get(ClaimID) then
            exit(Format(Claim.Status))
        else
            exit('Not Found');
    end;
}
