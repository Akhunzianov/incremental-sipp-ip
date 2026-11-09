// Persistent, deterministic eight-neighbor BFS for waypoint generation.
#include <algorithm>
#include <array>
#include <iostream>
#include <string>
#include <vector>
int main(){
    std::ios::sync_with_stdio(false);
    int h,w;if(!(std::cin>>h>>w)||h<1||w<1||h>256||w>256)return 2;
    std::vector<std::string> grid(h);for(auto& row:grid)if(!(std::cin>>row)||int(row.size())!=w)return 2;
    const std::array<int,8> dr{0,-1,0,1,1,1,-1,-1},dc{1,0,-1,0,1,-1,1,-1};
    auto route=[&](int sr,int sc,int gr,int gc){
        std::vector<int> path;
        if(sr<0||sr>=h||sc<0||sc>=w||gr<0||gr>=h||gc<0||gc>=w)return path;
        std::vector<int> parents(h*w,-2),queue;queue.reserve(h*w);
        int start=sr*w+sc,goal=gr*w+gc;parents[start]=-1;queue.push_back(start);
        for(size_t head=0;head<queue.size();++head){
            int cell=queue[head];
            if(cell==goal){for(int p=goal;p!=-1;p=parents[p])path.push_back(p);std::reverse(path.begin(),path.end());return path;}
            int r=cell/w,c=cell%w;
            for(int i=0;i<8;++i){int nr=r+dr[i],nc=c+dc[i];if(nr>=0&&nr<h&&nc>=0&&nc<w&&grid[nr][nc]=='.'&&parents[nr*w+nc]==-2){parents[nr*w+nc]=cell;queue.push_back(nr*w+nc);}}
        }
        return path;
    };
    int sr,sc,wr,wc,gr,gc;
    while(std::cin>>sr>>sc>>wr>>wc>>gr>>gc){
        auto first=route(sr,sc,wr,wc),second=route(wr,wc,gr,gc);
        if(first.empty()||second.empty()){std::cout<<"null\n"<<std::flush;continue;}
        first.insert(first.end(),second.begin()+1,second.end());
        std::cout<<'[';
        for(size_t i=0;i<first.size();++i){if(i)std::cout<<',';std::cout<<'['<<first[i]/w<<','<<first[i]%w<<']';}
        std::cout<<"]\n"<<std::flush;
    }
}
