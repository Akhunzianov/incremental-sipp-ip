// Independent test-only wrapper: no route instrumentation or source rewriting.
#include <bits/stdc++.h>
static unsigned int reference_seed;
class ReferenceDevice { public: unsigned int operator()()const{return reference_seed;} };
#define random_device ReferenceDevice
#define main upstream_generator_main
#include "../vendor/sipp-ip/src/generate_obstacles.cpp"
#undef main
#undef random_device
int main(){
    int n,sr,sc,gr,gc;
    std::cin>>H>>W>>MAP>>reference_seed>>n>>sr>>sc>>gr>>gc;
    for(int r=0;r<H;++r){std::string row;std::cin>>row;for(int c=0;c<W;++c)mp[r][c]=row[c]=='#';}
    mp[sr][sc]=mp[gr][gc]=true;
    generate_obstacles1(n);
    std::cout<<'[';bool comma=false;
    for(int r=0;r<H;++r)for(int c=0;c<W;++c)for(int t=0;t<MXT;++t)if(rsrv[r][c][t]){
        int end=t;while(end+1<MXT&&rsrv[r][c][end+1])++end;
        if(comma)std::cout<<',';comma=true;
        std::cout<<'['<<r<<','<<c<<','<<t*F<<','<<end*F<<']';t=end;
    }
    std::cout<<"]\n";
}
