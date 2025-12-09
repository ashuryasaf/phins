page 50103 "PHINS Billing List"
{
    ApplicationArea = All;
    Caption = 'Billing Management - Accounting Division';
    Editable = true;
    PageType = List;
    SourceTable = "PHINS Billing";
    UsageCategory = Documents;

    layout
    {
        area(content)
        {
            repeater(General)
            {
                field("Bill ID"; Rec."Bill ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the bill ID';
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
                field("Bill Date"; Rec."Bill Date")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the bill date';
                }
                field("Due Date"; Rec."Due Date")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the due date';
                }
                field("Amount Due"; Rec."Amount Due")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the amount due';
                }
                field("Amount Paid"; Rec."Amount Paid")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the amount paid';
                }
                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the payment status';
                }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(CreateBill)
            {
                ApplicationArea = All;
                Caption = 'Create Bill';
                Image = New;
                Promoted = true;
                PromotedCategory = New;
                trigger OnAction()
                begin
                    Rec.Init();
                    Rec.Insert(true);
                end;
            }
            action(RecordPayment)
            {
                ApplicationArea = All;
                Caption = 'Record Payment';
                Image = CheckList;
                trigger OnAction()
                begin
                    if Rec."Amount Due" > 0 then begin
                        Rec."Amount Paid" := Rec."Amount Due";
                        Rec.Status := Rec.Status::Paid;
                        Rec."Last Payment Date" := Today();
                        Rec.Modify();
                    end;
                end;
            }
            action(SendReminder)
            {
                ApplicationArea = All;
                Caption = 'Send Payment Reminder';
                Image = Email;
                trigger OnAction()
                begin
                    // Email notification to customer for payment
                    Message('Payment reminder sent to customer');
                end;
            }
        }
    }
}
