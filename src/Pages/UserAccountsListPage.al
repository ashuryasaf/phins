page 50108 "PHINS User Accounts"
{
    PageType = List;
    ApplicationArea = All;
    SourceTable = "PHINS User Account";
    Caption = 'PHINS User Accounts';

    layout
    {
        area(content)
        {
            repeater(Group)
            {
                field("User ID"; "User ID") { }
                field(Username; Username) { }
                field("Full Name"; "Full Name") { }
                field(Email; Email) { }
                field(Role; Role) { }
                field(Active; Active) { }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(NewUser)
            {
                ApplicationArea = All;
                Caption = 'New User';
                Image = New;
                Promoted = true;
                PromotedCategory = Process;
                RunObject = page 50109; // Card page
            }
        }
    }
}
