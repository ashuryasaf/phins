page 50102 "PHINS Claims List"
{
    ApplicationArea = All;
    Caption = 'Claims Management - Claims Division';
    Editable = true;
    PageType = List;
    SourceTable = "PHINS Claims";
    UsageCategory = Documents;

    layout
    {
        area(content)
        {
            repeater(General)
            {
                field("Claim ID"; Rec."Claim ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the claim ID';
                }
                field("Policy ID"; Rec."Policy ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the policy ID';
                }
                field("Customer ID"; Rec."Customer ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the customer ID';
                }
                field("Claim Date"; Rec."Claim Date")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the claim date';
                }
                field("Claim Amount"; Rec."Claim Amount")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the claim amount';
                }
                field("Approved Amount"; Rec."Approved Amount")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the approved amount';
                }
                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the claim status';
                }
                field(Priority; Rec.Priority)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the priority level';
                }
                field("Assigned To"; Rec."Assigned To")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the assigned claims adjuster';
                }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(NewClaim)
            {
                ApplicationArea = All;
                Caption = 'New Claim';
                Image = New;
                Promoted = true;
                PromotedCategory = New;
                trigger OnAction()
                begin
                    Rec.Init();
                    Rec.Insert(true);
                end;
            }
            action(ApproveClaim)
            {
                ApplicationArea = All;
                Caption = 'Approve Claim';
                Image = Approve;
                trigger OnAction()
                begin
                    if Rec.Status <> Rec.Status::Approved then begin
                        Rec.Status := Rec.Status::Approved;
                        Rec.Modify();
                    end;
                end;
            }
            action(RejectClaim)
            {
                ApplicationArea = All;
                Caption = 'Reject Claim';
                Image = Reject;
                trigger OnAction()
                begin
                    if Rec.Status <> Rec.Status::Rejected then begin
                        Rec.Status := Rec.Status::Rejected;
                        Rec.Modify();
                    end;
                end;
            }
        }
    }
}
