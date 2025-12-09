page 50107 "PHINS Customer Dashboard"
{
    ApplicationArea = All;
    Caption = 'My Account Dashboard';
    PageType = RoleCenter;
    SourceTable = "PHINS Customer";
    UsageCategory = Administration;

    layout
    {
        area(rolecenter)
        {
            group(Dashboard)
            {
                Caption = 'Dashboard';

                cuegroup(Policies)
                {
                    Caption = 'Insurance Policies';
                    CueGroupLayout = Wide;
                    field("ActivePolicies"; 0)
                    {
                        ApplicationArea = All;
                        Caption = 'Active Policies';
                        ToolTip = 'Number of active insurance policies';
                    }
                }

                cuegroup(Billing)
                {
                    Caption = 'Billing Status';
                    CueGroupLayout = Wide;
                    field("OutstandingBills"; 0)
                    {
                        ApplicationArea = All;
                        Caption = 'Bills Outstanding';
                        ToolTip = 'Number of outstanding bills';
                    }
                    field("TotalDueAmount"; 0)
                    {
                        ApplicationArea = All;
                        Caption = 'Total Amount Due';
                        ToolTip = 'Total amount due for payment';
                    }
                }

                cuegroup(Claims)
                {
                    Caption = 'Claims Summary';
                    CueGroupLayout = Wide;
                    field("OpenClaims"; 0)
                    {
                        ApplicationArea = All;
                        Caption = 'Open Claims';
                        ToolTip = 'Number of open claims';
                    }
                    field("ApprovedClaims"; 0)
                    {
                        ApplicationArea = All;
                        Caption = 'Approved Claims';
                        ToolTip = 'Number of approved claims awaiting payment';
                    }
                }
            }

            group(Navigation)
            {
                Caption = 'Quick Links';

                action(ViewPolicies)
                {
                    ApplicationArea = All;
                    Caption = 'View My Policies';
                    Image = Document;
                    trigger OnAction()
                    begin
                        Message('Navigate to policies list');
                    end;
                }

                action(ViewBilling)
                {
                    ApplicationArea = All;
                    Caption = 'View Billing Information';
                    Image = Payment;
                    trigger OnAction()
                    begin
                        Message('Navigate to billing');
                    end;
                }

                action(ViewClaims)
                {
                    ApplicationArea = All;
                    Caption = 'View My Claims';
                    Image = Checklist;
                    trigger OnAction()
                    begin
                        Message('Navigate to claims');
                    end;
                }

                action(MakePayment)
                {
                    ApplicationArea = All;
                    Caption = 'Make a Payment';
                    Image = Payment;
                    trigger OnAction()
                    begin
                        Message('Open payment portal');
                    end;
                }

                action(FileAClaim)
                {
                    ApplicationArea = All;
                    Caption = 'File a Claim';
                    Image = NewDocument;
                    trigger OnAction()
                    begin
                        Message('Open claim filing form');
                    end;
                }

                action(UpdateProfile)
                {
                    ApplicationArea = All;
                    Caption = 'Update My Profile';
                    Image = Edit;
                    trigger OnAction()
                    begin
                        Message('Open profile editing page');
                    end;
                }
            }
        }
    }
}
