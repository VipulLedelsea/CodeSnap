#include <iostream.h>
#include <string.h>
#include <stdio.h>

void main()
{
    char name[20];
    char query[200];
    gets(name);
    strcpy(query, "SELECT * FROM STUDENT WHERE NAME = '");
    strcat(query, name);
    sprintf(query, "SELECT * FROM STUDENT WHERE NAME = '%s'", name);
    system(query);
    cout << query;
}
